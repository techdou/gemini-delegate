#!/usr/bin/env python3
"""Authentication discovery and safe per-run selection for Gemini CLI delegation."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import platform
import tempfile
from typing import Any

AUTH_API_KEY = "gemini-api-key"
AUTH_VERTEX = "vertex-ai"
AUTH_GOOGLE = "oauth-personal"
AUTH_CHOICES = {"auto", "api-key", "vertex", "google"}

INDIVIDUAL_OAUTH_MARKERS = (
    "this client is no longer supported for gemini code assist for individuals",
    "migrate to the antigravity",
    "unsupported_client",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _selected_type(data: dict[str, Any]) -> str | None:
    # Current schema first; retain legacy shapes for diagnostics/migration.
    candidates = [
        _nested(data, "security", "auth", "selectedType"),
        _nested(data, "auth", "selectedType"),
        data.get("selectedAuthType"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _enforced_type(data: dict[str, Any]) -> str | None:
    value = _nested(data, "security", "auth", "enforcedType")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _system_defaults_path() -> Path:
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


def _system_settings_path() -> Path:
    override = os.environ.get("GEMINI_CLI_SYSTEM_SETTINGS_PATH")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Windows":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return root / "gemini-cli" / "settings.json"
    if system == "Darwin":
        return Path("/Library/Application Support/GeminiCli/settings.json")
    return Path("/etc/gemini-cli/settings.json")


def _home_root() -> Path:
    return Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()).expanduser()


def settings_layers(cwd: Path) -> list[tuple[str, Path]]:
    return [
        ("system-defaults", _system_defaults_path()),
        ("user", _home_root() / ".gemini" / "settings.json"),
        ("project", cwd / ".gemini" / "settings.json"),
        ("system-settings", _system_settings_path()),
    ]


def inspect_auth(cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or dict(os.environ)
    layers: list[dict[str, Any]] = []
    selected: str | None = None
    selected_source: str | None = None
    enforced: str | None = None
    enforced_source: str | None = None

    for layer, path in settings_layers(cwd):
        data = _load_json(path) if path.exists() else {}
        sel = _selected_type(data)
        enf = _enforced_type(data)
        if sel:
            selected, selected_source = sel, f"{layer}:{path}"
        if enf:
            enforced, enforced_source = enf, f"{layer}:{path}"
        layers.append({
            "layer": layer,
            "path": str(path),
            "exists": path.exists(),
            "selected_type": sel,
            "enforced_type": enf,
        })

    env_auth: str | None = None
    env_source: str | None = None
    if env.get("GOOGLE_GENAI_USE_GCA", "").lower() == "true":
        env_auth, env_source = AUTH_GOOGLE, "env:GOOGLE_GENAI_USE_GCA"
    elif env.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
        env_auth, env_source = AUTH_VERTEX, "env:GOOGLE_GENAI_USE_VERTEXAI"
    elif env.get("GOOGLE_GEMINI_BASE_URL"):
        env_auth, env_source = "gateway", "env:GOOGLE_GEMINI_BASE_URL"
    elif env.get("GEMINI_API_KEY"):
        env_auth, env_source = AUTH_API_KEY, "env:GEMINI_API_KEY"
    elif env.get("CLOUD_SHELL", "").lower() == "true" or env.get("GEMINI_CLI_USE_COMPUTE_ADC", "").lower() == "true":
        env_auth, env_source = "compute-adc", "env:compute-adc"

    # Gemini CLI non-interactive auth currently prefers configured selectedType over env detection.
    effective = selected or env_auth
    effective_source = selected_source or env_source

    has_vertex_project = bool(env.get("GOOGLE_CLOUD_PROJECT"))
    has_vertex_project_id = bool(env.get("GOOGLE_CLOUD_PROJECT_ID"))
    has_vertex_location = bool(env.get("GOOGLE_CLOUD_LOCATION"))
    vertex_configured = bool(env.get("GOOGLE_API_KEY")) or (has_vertex_project and has_vertex_location)

    warnings: list[str] = []
    if effective == AUTH_GOOGLE:
        warnings.append(
            "Google/Code Assist OAuth is no longer supported for individual Gemini CLI accounts. "
            "For third-party Agent delegation, prefer Gemini API Key or Vertex AI. Organization-managed Code Assist may differ."
        )
    if selected == AUTH_GOOGLE and env.get("GEMINI_API_KEY"):
        warnings.append(
            "GEMINI_API_KEY is set but saved settings select oauth-personal; the saved selectedType takes precedence in Headless mode unless explicitly overridden."
        )
    if env.get("GOOGLE_GENAI_USE_GCA", "").lower() == "true" and env.get("GEMINI_API_KEY"):
        warnings.append("GOOGLE_GENAI_USE_GCA=true takes precedence over GEMINI_API_KEY in environment-based auth detection.")

    return {
        "effective_type": effective,
        "effective_source": effective_source,
        "configured_selected_type": selected,
        "configured_selected_source": selected_source,
        "enforced_type": enforced,
        "enforced_source": enforced_source,
        "environment_detected_type": env_auth,
        "environment_detected_source": env_source,
        "credentials": {
            "GEMINI_API_KEY_set": bool(env.get("GEMINI_API_KEY")),
            "GOOGLE_API_KEY_set": bool(env.get("GOOGLE_API_KEY")),
            "GOOGLE_GENAI_USE_VERTEXAI": env.get("GOOGLE_GENAI_USE_VERTEXAI"),
            "GOOGLE_GENAI_USE_GCA": env.get("GOOGLE_GENAI_USE_GCA"),
            "GOOGLE_CLOUD_PROJECT_set": has_vertex_project,
            "GOOGLE_CLOUD_PROJECT_ID_set": has_vertex_project_id,
            "GOOGLE_CLOUD_LOCATION_set": has_vertex_location,
            "GOOGLE_APPLICATION_CREDENTIALS_set": bool(env.get("GOOGLE_APPLICATION_CREDENTIALS")),
            "vertex_configured": vertex_configured,
        },
        "layers": layers,
        "warnings": warnings,
        "third_party_recommendation": "Use Gemini API Key (Google AI Studio) or Vertex AI for Agent/Headless delegation.",
    }


def normalize_requested_auth(value: str) -> str:
    if value not in AUTH_CHOICES:
        raise ValueError(f"unsupported auth policy: {value}")
    return value


def _requested_to_type(value: str) -> str:
    return {
        "api-key": AUTH_API_KEY,
        "vertex": AUTH_VERTEX,
        "google": AUTH_GOOGLE,
    }[value]


def choose_auth(cwd: Path, requested: str = "auto", env: dict[str, str] | None = None) -> dict[str, Any]:
    requested = normalize_requested_auth(requested)
    env = env or dict(os.environ)
    status = inspect_auth(cwd, env)
    enforced = status.get("enforced_type")

    if requested == "auto":
        # For third-party/headless use, prefer supported provider auth paths over legacy consumer OAuth.
        if env.get("GEMINI_API_KEY"):
            desired = AUTH_API_KEY
            reason = "GEMINI_API_KEY is available"
        elif env.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true" or status["credentials"]["vertex_configured"]:
            desired = AUTH_VERTEX
            reason = "Vertex AI configuration is available"
        elif status.get("effective_type") in {AUTH_API_KEY, AUTH_VERTEX}:
            desired = str(status["effective_type"])
            reason = "saved Gemini CLI auth already selects an Agent-safe Headless method"
        elif status.get("effective_type") == AUTH_GOOGLE:
            return {
                "ok": False,
                "requested": requested,
                "detected": status,
                "error_kind": "individual_oauth_migration",
                "error": (
                    "Gemini CLI is configured for Google/Code Assist OAuth. Individual accounts are no longer served by this path. "
                    "For this third-party Agent Skill, configure GEMINI_API_KEY or Vertex AI. If this is an organization-managed Code Assist account, rerun with --auth google explicitly."
                ),
            }
        else:
            return {
                "ok": False,
                "requested": requested,
                "detected": status,
                "error_kind": "no_headless_auth",
                "error": (
                    "No Agent-safe Gemini Headless authentication was detected. Set GEMINI_API_KEY, or configure Vertex AI. "
                    "Personal Google OAuth is not used automatically by this Skill."
                ),
            }
    else:
        desired = _requested_to_type(requested)
        reason = f"explicit --auth {requested}"

    if enforced and enforced != desired:
        return {
            "ok": False,
            "requested": requested,
            "desired_type": desired,
            "detected": status,
            "error_kind": "enforced_auth_conflict",
            "error": f"Gemini CLI system policy enforces auth type {enforced!r}; refusing to override it with {desired!r}.",
        }

    if desired == AUTH_API_KEY:
        # A saved keychain key can exist even without the env var if settings already select gemini-api-key.
        if not env.get("GEMINI_API_KEY") and status.get("configured_selected_type") != AUTH_API_KEY:
            return {
                "ok": False,
                "requested": requested,
                "desired_type": desired,
                "detected": status,
                "error_kind": "missing_api_key",
                "error": "Gemini API Key auth requires GEMINI_API_KEY (or an already configured Gemini CLI API-key credential).",
            }
    elif desired == AUTH_VERTEX:
        if not status["credentials"]["vertex_configured"]:
            return {
                "ok": False,
                "requested": requested,
                "desired_type": desired,
                "detected": status,
                "error_kind": "missing_vertex_config",
                "error": "Vertex AI requires GOOGLE_API_KEY, or GOOGLE_CLOUD_PROJECT plus GOOGLE_CLOUD_LOCATION with valid ADC/service-account credentials.",
            }
    elif desired == AUTH_GOOGLE:
        # Explicit escape hatch for organization-managed Code Assist only.
        reason += "; intended only for organization-managed Code Assist/Workspace entitlement"

    current = status.get("effective_type")
    override_needed = bool(current and current != desired) or (status.get("configured_selected_type") not in {None, desired})
    if current is None:
        # Environment can select api-key/vertex without an override; google needs an explicit selected type/env.
        override_needed = desired == AUTH_GOOGLE

    return {
        "ok": True,
        "requested": requested,
        "desired_type": desired,
        "reason": reason,
        "override_needed": override_needed,
        "detected": status,
        "warning": (
            "Google OAuth is explicitly requested. This no longer works for Gemini CLI individual accounts; use only with an organization-managed entitlement."
            if desired == AUTH_GOOGLE else None
        ),
    }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def prepare_auth_environment(plan: dict[str, Any], base_env: dict[str, str] | None = None) -> tuple[tempfile.TemporaryDirectory[str] | None, dict[str, str]]:
    """Return a child env and optional temporary highest-precedence settings override.

    We refuse to replace an existing system-settings policy file. On ordinary personal machines where no
    system override exists, an explicit/auto API-key or Vertex choice can safely override stale user/project
    `oauth-personal` state for this child process without modifying persistent settings.
    """
    if not plan.get("ok"):
        raise ValueError(str(plan.get("error") or "invalid auth plan"))
    desired = str(plan["desired_type"])
    env = dict(base_env or os.environ)

    # Keep env auth deterministic and avoid the documented GCA > Vertex > API-key precedence trap.
    if desired == AUTH_API_KEY:
        env.pop("GOOGLE_GENAI_USE_GCA", None)
        env.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
    elif desired == AUTH_VERTEX:
        env.pop("GOOGLE_GENAI_USE_GCA", None)
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        # GEMINI_API_KEY is a different provider credential; remove from child to reduce ambiguity.
        env.pop("GEMINI_API_KEY", None)
    elif desired == AUTH_GOOGLE:
        env["GOOGLE_GENAI_USE_GCA"] = "true"
        env.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

    if not plan.get("override_needed"):
        return None, env

    system_path = _system_settings_path()
    if system_path.exists():
        raise PermissionError(
            f"Gemini system settings exist at {system_path}; refusing to replace/bypass administrator policy for per-run auth selection. "
            "Change the configured auth through your managed Gemini CLI setup instead."
        )

    injected = {"security": {"auth": {"selectedType": desired}}}
    td = tempfile.TemporaryDirectory(prefix="gemini-skill-auth-")
    path = Path(td.name) / "settings.json"
    path.write_text(json.dumps(injected, ensure_ascii=False, indent=2), encoding="utf-8")
    env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] = str(path)
    return td, env


def classify_auth_failure(text: str) -> dict[str, str] | None:
    low = text.lower()
    if any(marker in low for marker in INDIVIDUAL_OAUTH_MARKERS):
        return {
            "kind": "individual_oauth_migration",
            "message": (
                "Gemini CLI rejected the Google/Code Assist OAuth client for an individual account. "
                "Use GEMINI_API_KEY or Vertex AI for this Skill; use Antigravity if you specifically want Google's consumer-account CLI path."
            ),
        }
    if "please set an auth method" in low:
        return {"kind": "no_auth", "message": "No non-interactive Gemini auth is configured. Set GEMINI_API_KEY or configure Vertex AI."}
    if "must specify the gemini_api_key" in low:
        return {"kind": "missing_api_key", "message": "Gemini API-key auth is selected but GEMINI_API_KEY is unavailable."}
    if "when using vertex ai" in low and "must specify" in low:
        return {"kind": "missing_vertex_config", "message": "Vertex AI auth is selected but its project/location/API-key configuration is incomplete."}
    if "enforced authentication type" in low or "enforced authentication" in low:
        return {"kind": "enforced_auth_conflict", "message": "Gemini CLI authentication is constrained by system policy; the Skill will not bypass it."}
    return None
