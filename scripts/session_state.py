#!/usr/bin/env python3
"""Small local session-affinity registry shared by delegated CLI wrappers.

Stores only provider session metadata. It never stores task/prompt text or model responses.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Any

STATE_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state_root() -> Path:
    override = os.environ.get("FOREIGN_CLI_SKILL_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "foreign-cli-skills" / "state"
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "foreign-cli-skills"
    return Path.home() / ".local" / "state" / "foreign-cli-skills"


def session_key_from_env(provider: str) -> str | None:
    names = [f"{provider.upper()}_SKILL_SESSION_KEY", "FOREIGN_MODEL_SESSION_KEY"]
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _digest(provider: str, workspace: Path, session_key: str) -> str:
    raw = f"{provider}\0{os.path.normcase(str(workspace.resolve()))}\0{session_key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _workspace_hash(workspace: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(workspace.resolve())).encode("utf-8")).hexdigest()[:16]


def record_path(provider: str, workspace: Path, session_key: str, state_root: Path | None = None) -> Path:
    root = state_root or default_state_root()
    return root / provider / f"{_digest(provider, workspace, session_key)}.json"


def key_fingerprint(provider: str, workspace: Path, session_key: str) -> str:
    return _digest(provider, workspace, session_key)[:16]


def load_record(provider: str, workspace: Path, session_key: str, state_root: Path | None = None) -> dict[str, Any] | None:
    path = record_path(provider, workspace, session_key, state_root)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or obj.get("version") != STATE_VERSION:
        return None
    if obj.get("provider") != provider or obj.get("workspace") != str(workspace.resolve()):
        return None
    return obj


def save_record(provider: str, workspace: Path, session_key: str, data: dict[str, Any], state_root: Path | None = None) -> Path:
    path = record_path(provider, workspace, session_key, state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if os.name != "nt":
            path.parent.chmod(0o700)
    except OSError:
        pass
    payload = dict(data)
    payload.update({
        "version": STATE_VERSION,
        "provider": provider,
        "workspace": str(workspace.resolve()),
        "workspace_hash": _workspace_hash(workspace),
        "session_key_hash": key_fingerprint(provider, workspace, session_key),
        "updated_at": utc_now(),
    })
    payload.setdefault("created_at", payload["updated_at"])
    tmp = path.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        if os.name != "nt":
            tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def delete_record(provider: str, workspace: Path, session_key: str, state_root: Path | None = None) -> bool:
    path = record_path(provider, workspace, session_key, state_root)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def list_records(provider: str, state_root: Path | None = None) -> list[dict[str, Any]]:
    root = (state_root or default_state_root()) / provider
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for path in root.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("provider") == provider:
            obj = dict(obj)
            obj["record_file"] = str(path)
            out.append(obj)
    out.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
    return out


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class SessionLease:
    """Fail-fast lease preventing two wrapper processes from mutating one CLI session concurrently."""

    def __init__(self, provider: str, workspace: Path, session_key: str, state_root: Path | None = None):
        self.record = record_path(provider, workspace, session_key, state_root)
        self.path = self.record.with_suffix(".lock")
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                try:
                    obj = json.loads(self.path.read_text(encoding="utf-8"))
                    pid = int(obj.get("pid", 0))
                except Exception:
                    pid = 0
                if pid and process_alive(pid):
                    raise RuntimeError(f"session is already in use by wrapper process {pid}")
                try:
                    self.path.unlink()
                except OSError:
                    pass
                continue
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump({"pid": os.getpid(), "created_at": utc_now()}, f)
                self.acquired = True
                return
        raise RuntimeError("could not acquire session lease")

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.acquired = False

    def __enter__(self) -> "SessionLease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
