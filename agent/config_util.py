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
LOCAL_CONFIG_PATH = AGENT_DIR / "config.local.yaml"
_SESSION_OVERRIDES: dict[str, Any] = {}


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


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        value = yaml.safe_load(f) or {}
    return value if isinstance(value, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge ``override`` into ``base`` recursively and return ``base``."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config() -> dict[str, Any]:
    """Load effective configuration.

    Precedence is session overrides > ignored local config > tracked defaults.
    """
    config = _read_yaml(CONFIG_PATH)
    _deep_merge(config, _read_yaml(LOCAL_CONFIG_PATH))
    _deep_merge(config, _SESSION_OVERRIDES)
    return config


def set_session_overrides(*, backend: str | None = None, model: str | None = None) -> None:
    """Set process-local Web/CLI overrides without touching persistent files."""
    _SESSION_OVERRIDES.clear()
    if backend is None and model is None:
        return
    effective_backend = backend or load_config().get("agent", {}).get("backend", "local")
    agent: dict[str, Any] = {"backend": effective_backend}
    if model is not None:
        agent[effective_backend] = {"model": model}
    _SESSION_OVERRIDES["agent"] = agent


def clear_session_overrides() -> None:
    _SESSION_OVERRIDES.clear()


def has_session_overrides() -> bool:
    return bool(_SESSION_OVERRIDES)


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
        "backend": "local",
        "tolerance_seconds": 1.0,
        "max_rounds": 10,
        "max_low_conf_rounds": 2,
        "temperature": 0.2,
        "remote": {
            "provider": "dashscope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "local": {
            "provider": "ollama",
            "model": "tensile-qwen35:9b",
            "base_url": "http://localhost:11434/v1",
            "reasoning_effort": "none",
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
    """Backward-compatible alias that persists the remote model locally."""
    save_remote_model(model)


def _write_local_config(config: dict[str, Any]) -> None:
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def save_remote_model(model: str, activate: bool = False) -> None:
    """Save remote model and optionally activate remote backend.

    When ``activate`` is True, ``agent.backend`` is set to ``"remote"``.
    Otherwise the backend setting is left unchanged.
    """
    config = _read_yaml(LOCAL_CONFIG_PATH)
    agent = config.setdefault("agent", {})
    agent.setdefault("remote", {})["model"] = model
    if activate:
        agent["backend"] = "remote"
    _write_local_config(config)


def save_active_config(
    backend: str,
    model: str,
    *,
    reasoning_effort: str = "none",
) -> None:
    """Persist an active local/remote choice in the ignored local config."""
    if backend not in {"local", "remote"}:
        raise ValueError("backend must be 'local' or 'remote'")
    if not model.strip():
        raise ValueError("model must not be empty")
    if reasoning_effort not in {"none", "low", "medium", "high"}:
        raise ValueError("unsupported reasoning_effort")
    config = _read_yaml(LOCAL_CONFIG_PATH)
    agent = config.setdefault("agent", {})
    agent["backend"] = backend
    selected = agent.setdefault(backend, {})
    selected["model"] = model.strip()
    if backend == "local":
        selected["reasoning_effort"] = reasoning_effort
    _write_local_config(config)


def get_active_model_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a secret-free snapshot of the selected decision backend."""
    config = config or load_config()
    agent = config.get("agent", {})
    backend = agent.get("backend", "unconfigured")
    selected = agent.get(backend, {}) if backend in {"local", "remote"} else {}
    return {
        "backend": backend,
        "provider": selected.get("provider"),
        "model": selected.get("model"),
        "base_url": selected.get("base_url"),
        "reasoning_effort": selected.get("reasoning_effort", "none"),
    }


def _ollama_api_root(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value[:-3] if value.endswith("/v1") else value


def list_local_models(base_url: str = "http://localhost:11434/v1") -> dict[str, Any]:
    """Return installed Ollama models and stable health information."""
    try:
        response = requests.get(f"{_ollama_api_root(base_url)}/api/tags", timeout=3)
        response.raise_for_status()
        models = []
        for item in response.json().get("models", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            models.append({
                "id": item["name"],
                "digest": item.get("digest"),
                "size": item.get("size"),
                "modified_at": item.get("modified_at"),
            })
        return {"ok": True, "models": sorted(models, key=lambda item: item["id"]), "error_kind": None}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "models": [], "error_kind": "service_unavailable", "warning": "Ollama 未启动，请运行 ollama serve"}
    except requests.exceptions.Timeout:
        return {"ok": False, "models": [], "error_kind": "timeout", "warning": "Ollama 响应超时"}
    except (requests.exceptions.RequestException, AttributeError, ValueError, TypeError) as exc:
        return {"ok": False, "models": [], "error_kind": "invalid_response", "warning": str(exc)}


def get_local_model_digest(model: str, base_url: str = "http://localhost:11434/v1") -> str | None:
    result = list_local_models(base_url)
    for item in result.get("models", []):
        if item.get("id") == model:
            return item.get("digest")
    return None


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
