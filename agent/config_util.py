"""Configuration utilities for TensileAgent.

Handles reading/writing API keys, checking config status,
and listing available models from OpenAI-compatible endpoints.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
import requests

# ── Paths ──

AGENT_DIR = Path(__file__).parent
PROJECT_DIR = AGENT_DIR.parent
DOT_ENV_PATH = AGENT_DIR / ".env"
CONFIG_PATH = AGENT_DIR / "config.yaml"


# ── .env file helpers ──

def _load_dotenv() -> dict[str, str]:
    """Load key=value pairs from agent/.env."""
    if not DOT_ENV_PATH.exists():
        return {}
    result: dict[str, str] = {}
    with open(DOT_ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip("\"'")
    return result


def _write_dotenv(key: str, value: str) -> None:
    """Write or update a single KEY=VALUE entry in agent/.env.

    Preserves existing comments and other entries.
    """
    lines: list[str] = []
    updated = False
    if DOT_ENV_PATH.exists():
        with open(DOT_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    updated = True
                else:
                    lines.append(line)
    if not updated:
        lines.append(f"{key}={value}\n")
    DOT_ENV_PATH.write_text("".join(lines), encoding="utf-8")


# ── Public API ──

def get_api_key() -> str | None:
    """Get API key from environment variable LLM_API_KEY or agent/.env.

    Priority: LLM_API_KEY env var > agent/.env > None.
    """
    env_key = os.environ.get("LLM_API_KEY")
    if env_key:
        return env_key
    dotenv = _load_dotenv()
    return dotenv.get("LLM_API_KEY")


def save_api_key(api_key: str) -> None:
    """Save API key to agent/.env."""
    _write_dotenv("LLM_API_KEY", api_key)


def load_config() -> dict[str, Any]:
    """Load and return the YAML configuration at agent/config.yaml.

    Returns an empty dict when config.yaml does not exist.
    """
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_active_backend() -> str:
    """Return the currently active backend: 'remote', 'local', or 'unconfigured'."""
    config = load_config()
    backend = config.get("agent", {}).get("backend", "")
    if backend in ("remote", "local"):
        return backend
    return "unconfigured"


def is_remote_configured() -> bool:
    """Check if remote backend has both API key and model configured."""
    config = load_config()
    agent_cfg = config.get("agent", {})
    remote_cfg = agent_cfg.get("remote", {})
    has_api_key = bool(get_api_key())
    has_model = bool(remote_cfg.get("model"))
    return agent_cfg.get("backend") == "remote" and has_api_key and has_model


def get_configured_model() -> str | None:
    """Get the currently configured remote model name."""
    config = load_config()
    return config.get("agent", {}).get("remote", {}).get("model")


_MINIMAL_CONFIG: dict[str, Any] = {
    "agent": {
        "backend": "remote",
        "tolerance_seconds": 1.0,
        "max_rounds": 10,
        "max_low_conf_rounds": 2,
        "temperature": 0.7,
        "remote": {
            "provider": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "local": {
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
        },
    },
    "backend": {
        "api_url": "http://localhost:8000/v1",
        "model": "minicpmv4_5",
    },
}


def _deep_merge_defaults(config: dict, defaults: dict) -> dict:
    """Recursively merge defaults into config, preserving existing values."""
    for key, default_value in defaults.items():
        if key not in config:
            config[key] = default_value
        elif isinstance(default_value, dict) and isinstance(config[key], dict):
            _deep_merge_defaults(config[key], default_value)
    return config


def save_model(model: str) -> None:
    """Update the remote model in agent/config.yaml.

    Always ensures a minimal set of required config keys exist via
    ``_deep_merge_defaults``, then writes ``agent.remote.model``.
    """
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    _deep_merge_defaults(config, _MINIMAL_CONFIG)
    config["agent"]["remote"]["model"] = model
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def save_remote_model(model: str, activate: bool = False) -> None:
    """Save remote model and optionally activate remote backend.

    When ``activate`` is True, ``agent.backend`` is set to ``"remote"``.
    Otherwise the backend setting is left unchanged.
    """
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}
    _deep_merge_defaults(config, _MINIMAL_CONFIG)
    config.setdefault("agent", {}).setdefault("remote", {})["model"] = model
    if activate:
        config["agent"]["backend"] = "remote"
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def list_available_models(
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key: str | None = None,
) -> dict:
    """Query an OpenAI-compatible endpoint for available models.

    Returns:
        {
            "ok": True/False,
            "models": [...],           # model IDs when successful
            "error_kind": str | None,   # "network_error" / "auth_error" / None
            "warning": str | None,      # human-readable hint
        }
    """
    key = api_key or get_api_key()
    if not key:
        return {
            "ok": False,
            "models": [],
            "error_kind": "auth_error",
            "warning": "未提供 API Key",
        }
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        try:
            data = resp.json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        except (ValueError, KeyError, TypeError) as e:
            return {
                "ok": False,
                "models": [],
                "error_kind": "network_error",
                "warning": "平台返回数据格式异常",
            }
        sorted_ids = sorted(models)
        if not sorted_ids:
            return {
                "ok": True,
                "models": [],
                "error_kind": None,
                "warning": "平台返回空模型列表，可手动输入模型名",
            }
        return {
            "ok": True,
            "models": sorted_ids,
            "error_kind": None,
            "warning": None,
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "models": [],
            "error_kind": "network_error",
            "warning": "无法连接百炼平台，请检查网络",
        }
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "models": [],
            "error_kind": "network_error",
            "warning": "无法连接百炼平台，请检查网络",
        }
    except requests.exceptions.HTTPError:
        return {
            "ok": False,
            "models": [],
            "error_kind": "auth_error",
            "warning": "API Key 验证失败",
        }
