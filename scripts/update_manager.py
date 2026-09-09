#!/usr/bin/env python3
"""Self-maintenance helpers for provider CLI skills.

Security properties:
- normal task execution never performs network update checks;
- remote manifests/artifacts must use HTTPS;
- candidate artifacts require SHA-256 verification;
- ZIP extraction rejects traversal, links, and oversized archives;
- candidates are validated before install;
- current skill is backed up and restored on failed replacement.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILES = 600
VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def metadata_path(root: Path | None = None) -> Path:
    return (root or skill_root()) / "skill.json"


def load_skill_metadata(root: Path | None = None) -> dict[str, Any]:
    path = metadata_path(root)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"invalid skill metadata: {path}")
    return obj


def state_root() -> Path:
    override = os.environ.get("FOREIGN_CLI_SKILL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "foreign-cli-skills" / "state"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "foreign-cli-skills"
    return Path.home() / ".local" / "state" / "foreign-cli-skills"


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    m = VERSION_RE.search(str(value))
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def compare_versions(a: str, b: str) -> int:
    av = parse_version(a)
    bv = parse_version(b)
    if av is None or bv is None:
        raise ValueError(f"could not parse semantic version: {a!r}, {b!r}")
    return (av > bv) - (av < bv)


def compatibility_status(installed_version: str | None, metadata: dict[str, Any]) -> dict[str, Any]:
    compat = metadata.get("compatibility") or {}
    minimum = compat.get("min_cli")
    tested = compat.get("tested_through_cli")
    parsed = parse_version(installed_version)
    result: dict[str, Any] = {
        "installed": installed_version,
        "minimum": minimum,
        "tested_through": tested,
        "status": "unknown",
        "blocking": False,
    }
    if parsed is None:
        result["reason"] = "CLI version could not be parsed"
        return result
    if minimum and compare_versions(installed_version or "", str(minimum)) < 0:
        result.update(status="too_old", blocking=True, reason="installed CLI is below the skill minimum")
        return result
    if tested and compare_versions(installed_version or "", str(tested)) > 0:
        result.update(status="untested_newer", blocking=False, reason="installed CLI is newer than the range verified by this skill")
        return result
    result.update(status="compatible", blocking=False)
    return result


def manifest_source(provider: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    for name in (f"{provider.upper()}_SKILL_MANIFEST_URL", "FOREIGN_CLI_SKILL_MANIFEST_URL"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _read_local(path: Path, max_bytes: int) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if path.stat().st_size > max_bytes:
        raise ValueError(f"file exceeds size limit: {path}")
    return path.read_bytes()


def read_source(source: str, *, max_bytes: int, timeout: int = 20) -> bytes:
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        if parsed.scheme != "https":
            raise ValueError("remote update sources must use HTTPS")
        req = Request(source, headers={"User-Agent": "foreign-cli-skills-updater/1.4"})
        with urlopen(req, timeout=timeout) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ValueError("remote object exceeds size limit")
            data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("remote object exceeds size limit")
        return data
    if parsed.scheme == "file":
        return _read_local(Path(parsed.path).expanduser().resolve(), max_bytes)
    if parsed.scheme:
        raise ValueError(f"unsupported update source scheme: {parsed.scheme}")
    return _read_local(Path(source).expanduser().resolve(), max_bytes)


def load_release_manifest(source: str, provider: str, *, timeout: int = 20) -> dict[str, Any]:
    raw = read_source(source, max_bytes=1024 * 1024, timeout=timeout)
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict) or obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported release manifest schema")
    if obj.get("provider") != provider:
        raise ValueError(f"manifest provider mismatch: expected {provider!r}")
    channels = obj.get("channels")
    releases = obj.get("releases")
    if not isinstance(channels, dict) or not isinstance(releases, dict):
        raise ValueError("manifest must contain channels and releases objects")
    return obj


def select_release(manifest: dict[str, Any], *, channel: str = "stable", version: str | None = None) -> tuple[str, dict[str, Any]]:
    releases = manifest["releases"]
    selected = version or manifest["channels"].get(channel)
    if not selected or selected not in releases:
        raise ValueError(f"release not found for channel/version: {version or channel}")
    release = releases[selected]
    if not isinstance(release, dict):
        raise ValueError("invalid release entry")
    artifact = release.get("artifact_url")
    digest = release.get("sha256")
    if not isinstance(artifact, str) or not artifact:
        raise ValueError("release is missing artifact_url")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValueError("release is missing a valid SHA-256")
    return str(selected), release


def update_cache_path(provider: str) -> Path:
    return state_root() / "updates" / provider / "last-check.json"


def save_update_cache(provider: str, payload: dict[str, Any]) -> None:
    path = update_cache_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["checked_at"] = utc_now()
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_update_cache(provider: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(update_cache_path(provider).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def check_update(provider: str, source: str, *, channel: str = "stable", timeout: int = 20) -> dict[str, Any]:
    metadata = load_skill_metadata()
    manifest = load_release_manifest(source, provider, timeout=timeout)
    latest, release = select_release(manifest, channel=channel)
    current = str(metadata["version"])
    cmp = compare_versions(latest, current)
    payload = {
        "provider": provider,
        "current_version": current,
        "channel": channel,
        "latest_version": latest,
        "update_available": cmp > 0,
        "ahead_of_manifest": cmp < 0,
        "release": {
            "breaking": bool(release.get("breaking", False)),
            "notes": release.get("notes"),
            "compatibility": release.get("compatibility") or {},
        },
        "source": source,
    }
    save_update_cache(provider, payload)
    return payload


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_artifact(source: str, target: Path, *, timeout: int = 60) -> None:
    data = read_source(source, max_bytes=MAX_ARCHIVE_BYTES, timeout=timeout)
    target.write_bytes(data)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def safe_extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise ValueError("update archive contains too many files")
        total = 0
        for info in infos:
            total += int(info.file_size)
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("update archive expands beyond size limit")
            if _is_zip_symlink(info):
                raise ValueError(f"update archive contains a symbolic link: {info.filename}")
            name = info.filename.replace("\\", "/")
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"unsafe path in update archive: {info.filename}")
        zf.extractall(destination)


def candidate_root(extracted: Path, provider: str) -> Path:
    direct = extracted / provider
    if direct.is_dir():
        return direct
    # Accept an archive whose root itself is the skill directory.
    if (extracted / "SKILL.md").is_file() and (extracted / "skill.json").is_file():
        return extracted
    raise ValueError(f"update archive must contain a top-level {provider}/ skill directory")


def validate_candidate(candidate: Path, provider: str, expected_version: str | None = None) -> dict[str, Any]:
    required = [
        "SKILL.md",
        "skill.json",
        "scripts/run.py",
        "scripts/model_catalog.py",
        "scripts/session_state.py",
        "scripts/update_manager.py",
        "references/security.md",
        "references/official-cli.md",
        "references/model-control.md",
        "references/session-cache.md",
        "references/maintenance.md",
        "references/workflows.md",
        "evals/evals.json",
    ]
    missing = [rel for rel in required if not (candidate / rel).is_file()]
    if missing:
        raise ValueError("candidate is missing required files: " + ", ".join(missing))
    meta = load_skill_metadata(candidate)
    if meta.get("name") != provider:
        raise ValueError("candidate skill name/provider mismatch")
    if expected_version and str(meta.get("version")) != expected_version:
        raise ValueError(f"candidate version mismatch: expected {expected_version}, got {meta.get('version')}")
    text = (candidate / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n") or f"name: {provider}" not in text.split("---", 2)[1]:
        raise ValueError("candidate SKILL.md frontmatter is invalid")
    evals = json.loads((candidate / "evals" / "evals.json").read_text(encoding="utf-8"))
    if evals.get("skill_name") != provider or not isinstance(evals.get("evals"), list):
        raise ValueError("candidate eval metadata is invalid")
    compiled = []
    for py in sorted((candidate / "scripts").glob("*.py")):
        py_compile.compile(str(py), doraise=True)
        compiled.append(py.name)
    proc = subprocess.run(
        [sys.executable, str(candidate / "scripts" / "run.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(candidate),
    )
    if proc.returncode != 0:
        raise ValueError("candidate runtime smoke check failed: " + (proc.stderr or proc.stdout).strip())
    return {"name": provider, "version": str(meta.get("version")), "compiled_scripts": compiled, "runtime_help_ok": True}


def backups_root(provider: str) -> Path:
    return state_root() / "backups" / provider


def create_backup(provider: str, source: Path, version: str) -> Path:
    root = backups_root(provider)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / f"{version}-{stamp}-{os.getpid()}"
    shutil.copytree(source, dest)
    (dest / "backup-meta.json").write_text(
        json.dumps({"provider": provider, "version": version, "created_at": utc_now(), "source": str(source)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def list_backups(provider: str) -> list[dict[str, Any]]:
    root = backups_root(provider)
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            meta = json.loads((path / "backup-meta.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("provider") == provider:
            meta = dict(meta)
            meta["path"] = str(path)
            out.append(meta)
    out.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return out


def _swap_directory(target: Path, candidate: Path) -> None:
    old = target.parent / f".{target.name}.replace-old-{os.getpid()}"
    if old.exists():
        shutil.rmtree(old)
    os.replace(target, old)
    try:
        os.replace(candidate, target)
    except Exception:
        os.replace(old, target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def install_release(
    provider: str,
    source: str,
    *,
    channel: str = "stable",
    version: str | None = None,
    timeout: int = 60,
    installed_cli_version: str | None = None,
) -> dict[str, Any]:
    current_root = skill_root()
    current_meta = load_skill_metadata(current_root)
    manifest = load_release_manifest(source, provider, timeout=min(timeout, 30))
    selected, release = select_release(manifest, channel=channel, version=version)
    current_version = str(current_meta["version"])
    if compare_versions(selected, current_version) <= 0 and version is None:
        return {"provider": provider, "updated": False, "current_version": current_version, "selected_version": selected, "reason": "no newer release selected"}
    with tempfile.TemporaryDirectory(prefix=f".{provider}-download-", dir=str(current_root.parent)) as td:
        td_path = Path(td)
        archive = td_path / "candidate.zip"
        download_artifact(str(release["artifact_url"]), archive, timeout=timeout)
        actual = sha256_file(archive)
        expected = str(release["sha256"]).lower()
        if actual.lower() != expected:
            raise ValueError(f"SHA-256 mismatch: expected {expected}, got {actual}")
        extracted = td_path / "extracted"
        extracted.mkdir()
        safe_extract_zip(archive, extracted)
        candidate = candidate_root(extracted, provider)
        validation = validate_candidate(candidate, provider, selected)
        candidate_meta = load_skill_metadata(candidate)
        candidate_compat = compatibility_status(installed_cli_version, candidate_meta) if installed_cli_version else {"status": "unknown", "blocking": False, "installed": None}
        if candidate_compat.get("blocking"):
            raise ValueError(
                f"candidate Skill {selected} is incompatible with installed CLI {installed_cli_version}: "
                f"{candidate_compat.get('reason') or candidate_compat.get('status')}"
            )
        backup = create_backup(provider, current_root, current_version)
        staged = current_root.parent / f".{provider}.candidate-{os.getpid()}"
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(candidate, staged)
        try:
            _swap_directory(current_root, staged)
        except Exception:
            if not current_root.exists() and backup.exists():
                shutil.copytree(backup, current_root)
            raise
    return {
        "provider": provider,
        "updated": True,
        "from_version": current_version,
        "to_version": selected,
        "backup": str(backup),
        "validation": validation,
        "cli_compatibility": candidate_compat,
        "breaking": bool(release.get("breaking", False)),
        "notes": release.get("notes"),
    }


def rollback(provider: str, *, version: str | None = None) -> dict[str, Any]:
    current_root = skill_root()
    current = load_skill_metadata(current_root)
    backups = list_backups(provider)
    if version:
        backups = [b for b in backups if str(b.get("version")) == version]
    if not backups:
        raise FileNotFoundError("no matching backup is available")
    chosen = Path(str(backups[0]["path"]))
    validate_candidate(chosen, provider, str(backups[0]["version"]))
    safety_backup = create_backup(provider, current_root, str(current["version"]))
    staged = current_root.parent / f".{provider}.rollback-{os.getpid()}"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(chosen, staged, ignore=shutil.ignore_patterns("backup-meta.json"))
    _swap_directory(current_root, staged)
    return {
        "provider": provider,
        "rolled_back": True,
        "from_version": str(current["version"]),
        "to_version": str(backups[0]["version"]),
        "restored_from": str(chosen),
        "safety_backup": str(safety_backup),
    }


def update_info(provider: str) -> dict[str, Any]:
    meta = load_skill_metadata()
    source = manifest_source(provider)
    return {
        "provider": provider,
        "skill": meta,
        "manifest_source_configured": bool(source),
        "manifest_source": source,
        "cached_update_check": read_update_cache(provider),
        "backups": list_backups(provider),
        "network_policy": "No update network request occurs during normal task execution or --update-info. Use --check-update explicitly.",
    }
