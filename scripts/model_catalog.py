#!/usr/bin/env python3
"""Model selectors, config discovery, probing, and thinking helpers for Gemini CLI."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

OFFICIAL_SELECTORS = {
    "auto": "Recommended automatic model routing.",
    "pro": "Prefer the Pro tier for complex work and reasoning.",
    "flash": "Prefer the Flash tier for faster work.",
    "flash-lite": "Prefer the lightweight Flash tier for simple/high-throughput work.",
}

# Google documents this cross-provider mapping for Gemini 2.5 reasoning effort.
THINKING_BUDGETS_25 = {
    "none": 0,
    "minimal": 1024,
    "low": 1024,
    "medium": 8192,
    "high": 24576,
}
THINKING_LEVELS_3 = {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def settings_paths(cwd: Path) -> list[tuple[str, Path]]:
    home_root = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()).expanduser()
    return [
        ("user", home_root / ".gemini" / "settings.json"),
        ("project", cwd / ".gemini" / "settings.json"),
    ]


def discover_known_models(cwd: Path) -> dict[str, Any]:
    aliases: dict[str, dict[str, Any]] = {
        k: {"name": k, "source": "official-selector", "description": v}
        for k, v in OFFICIAL_SELECTORS.items()
    }
    exact_models: dict[str, dict[str, Any]] = {}
    configured_model: str | None = None
    configured_source = None

    for layer, path in settings_paths(cwd):
        data = _load_json(path)
        model_name = (data.get("model") or {}).get("name") if isinstance(data.get("model"), dict) else None
        if isinstance(model_name, str):
            configured_model = model_name
            configured_source = f"{layer}:{path}"
        mc = data.get("modelConfigs") if isinstance(data.get("modelConfigs"), dict) else {}
        custom = mc.get("customAliases") if isinstance(mc.get("customAliases"), dict) else {}
        for name, spec in custom.items():
            if isinstance(name, str):
                aliases[name] = {"name": name, "source": f"{layer}-custom-alias", "config": spec}
        defs = mc.get("modelDefinitions") if isinstance(mc.get("modelDefinitions"), dict) else {}
        for name, spec in defs.items():
            if isinstance(name, str):
                exact_models[name] = {"name": name, "source": f"{layer}-model-definition", "metadata": spec}

    env_model = os.environ.get("GEMINI_MODEL")
    if env_model:
        configured_model = env_model
        configured_source = "env:GEMINI_MODEL"

    return {
        "source": "Gemini CLI selectors + local settings",
        "selectors": list(aliases.values()),
        "exact_models": list(exact_models.values()),
        "configured_model": configured_model,
        "configured_model_source": configured_source,
        "note": "Gemini Headless CLI has no authoritative account model-list command. Use --probe-model to verify a concrete model or selector in the current authentication context.",
    }


def infer_family(model: str) -> str | None:
    low = model.lower()
    if "2.5" in low:
        return "gemini-2.5"
    if low.startswith("gemini-3") or "gemini-3" in low:
        return "gemini-3"
    return None


def thinking_override(model: str, thinking: str) -> dict[str, Any]:
    if thinking == "auto":
        return {}
    family = infer_family(model)
    if not family:
        raise ValueError(
            "explicit --thinking requires a concrete Gemini 2.5 or Gemini 3.x model id; "
            "selectors such as auto/pro/flash should use --thinking auto"
        )
    if family == "gemini-2.5":
        return {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": THINKING_BUDGETS_25[thinking]}}
    if thinking == "none":
        raise ValueError("Gemini 3.x reasoning cannot be fully disabled; choose minimal/low/medium/high or auto")
    return {"thinkingConfig": {"includeThoughts": True, "thinkingLevel": THINKING_LEVELS_3[thinking]}}


def profile_defaults(profile: str | None) -> tuple[str | None, str]:
    if profile == "fast":
        return "flash", "auto"
    if profile == "balanced":
        return "auto", "auto"
    if profile == "deep":
        return "pro", "auto"
    return None, "auto"


def _default_system_defaults_path() -> Path:
    override = os.environ.get("GEMINI_CLI_SYSTEM_DEFAULTS_PATH")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Windows":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return root / "gemini-cli" / "system-defaults.json"
    if system == "Darwin":
        return Path("/Library/Application Support/GeminiCli/system-defaults.json")
    return Path("/etc/gemini-cli/system-defaults.json")


def make_run_defaults(model: str, thinking: str, alias: str) -> tuple[tempfile.TemporaryDirectory[str] | None, str | None]:
    override = thinking_override(model, thinking)
    if not override:
        return None, None
    defaults_path = _default_system_defaults_path()
    if defaults_path.exists():
        try:
            raw_existing = json.loads(defaults_path.read_text(encoding="utf-8"))
            if not isinstance(raw_existing, dict):
                raise ValueError("root must be an object")
            existing = raw_existing
        except Exception as exc:
            raise ValueError(f"cannot safely preserve existing Gemini system defaults at {defaults_path}: {exc}") from exc
    else:
        existing = {}
    injected = {
        "modelConfigs": {
            "customAliases": {
                alias: {
                    "modelConfig": {
                        "model": model,
                        "generateContentConfig": override,
                    }
                }
            }
        }
    }
    merged = _deep_merge(existing, injected)
    td = tempfile.TemporaryDirectory(prefix="gemini-skill-defaults-")
    path = Path(td.name) / "system-defaults.json"
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return td, str(path)


def probe_model(cli: str, cwd: Path, model: str, timeout: int = 60, env: dict[str, str] | None = None) -> dict[str, Any]:
    cmd = [cli, "--output-format", "json", "--approval-mode", "default", "--model", model, "-p", "Reply with exactly: OK"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(cwd), env=env)
    result: dict[str, Any] = {"model": model, "available": False, "exit_code": proc.returncode}
    if proc.returncode != 0:
        result["error"] = (proc.stderr or proc.stdout).strip()
        return result
    try:
        obj = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["error"] = "Gemini returned non-JSON output"
        return result
    response = obj.get("response") if isinstance(obj, dict) else None
    result["available"] = isinstance(response, str)
    result["response"] = response
    return result
