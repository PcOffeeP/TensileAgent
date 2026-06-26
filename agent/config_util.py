"""Configuration utilities for TensileAgent.

Handles reading/writing API keys, checking config status,
and listing available models from OpenAI-compatible endpoints.
"""

from __future__ import annotations

import os
import re
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
    """Load and return the YAML configuration at agent/config.yaml."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


def save_model(model: str) -> None:
    """Update the remote model in agent/config.yaml."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    # Replace model field under agent.remote
    content = re.sub(
        r'(?<=^remote:\n\s+)model:.*',
        f"model: {model}",
        content,
        flags=re.MULTILINE,
    )
    CONFIG_PATH.write_text(content, encoding="utf-8")


def list_available_models(
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key: str | None = None,
) -> list[str]:
    """Query an OpenAI-compatible endpoint for available models.

    Returns a list of model IDs. Uses the /v1/models endpoint.
    """
    key = api_key or get_api_key()
    if not key:
        return []
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = [m["id"] for m in data.get("data", []) if isinstance(m, dict)]
        return sorted(models)
    except Exception:
        return []
