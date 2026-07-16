"""Tests for agent/config_util.py.

All file-system tests use ``tmp_path`` and ``monkeypatch`` to avoid
touching the real ``agent/.env`` or ``agent/config.yaml``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from agent.config_util import (
    _deep_merge_defaults,
    _MINIMAL_CONFIG,
    get_active_backend,
    get_api_key,
    get_local_model_digest,
    list_available_models,
    save_api_key,
    save_remote_model,
    clear_session_overrides,
    load_config,
    save_active_config,
    set_session_overrides,
    list_local_models,
)


@pytest.fixture(autouse=True)
def isolate_local_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    clear_session_overrides()
    yield
    clear_session_overrides()


# ── get_api_key ────────────────────────────────────────────────────────────


class TestGetApiKey:
    def test_env_var_has_priority_over_dotenv(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM_API_KEY env var exists → return env var, never read .env."""
        dotenv = tmp_path / ".env"
        dotenv.write_text("LLM_API_KEY=sk-from-dotenv\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.DOT_ENV_PATH", dotenv)
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")

        result = get_api_key()

        assert result == "sk-from-env"

    def test_no_env_no_dotenv_file_returns_none(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No LLM_API_KEY env var; DOT_ENV_PATH file doesn't exist → None."""
        nonexistent = tmp_path / "does_not_exist.env"
        monkeypatch.setattr("agent.config_util.DOT_ENV_PATH", nonexistent)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        result = get_api_key()

        assert result is None

    def test_no_env_dotenv_file_has_key_returns_dotenv_value(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No LLM_API_KEY env var; .env file exists with key → return value."""
        dotenv = tmp_path / ".env"
        dotenv.write_text("LLM_API_KEY=sk-dotenv\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.DOT_ENV_PATH", dotenv)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        result = get_api_key()

        assert result == "sk-dotenv"


# ── save_api_key ───────────────────────────────────────────────────────────


class TestSaveApiKey:
    def test_writes_new_dotenv_file(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Write new .env file → file created with LLM_API_KEY=sk-saved."""
        dotenv = tmp_path / ".env"
        # Ensure file does not exist yet
        assert not dotenv.exists()
        monkeypatch.setattr("agent.config_util.DOT_ENV_PATH", dotenv)

        save_api_key("sk-saved")

        assert dotenv.exists()
        content = dotenv.read_text(encoding="utf-8")
        assert "LLM_API_KEY=sk-saved" in content


# ── get_active_backend ─────────────────────────────────────────────────────


class TestGetActiveBackend:
    def test_remote_backend(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """config has agent.backend: 'remote' → return 'remote'."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("agent:\n  backend: remote\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.CONFIG_PATH", config_file)

        assert get_active_backend() == "remote"

    def test_local_backend(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        """config has agent.backend: 'local' → return 'local'."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("agent:\n  backend: local\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.CONFIG_PATH", config_file)

        assert get_active_backend() == "local"

    def test_unconfigured_when_backend_missing(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """config has no agent.backend → return 'unconfigured'."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("agent:\n  tolerance_seconds: 1.0\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.CONFIG_PATH", config_file)

        assert get_active_backend() == "unconfigured"

    def test_unconfigured_when_config_file_missing(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONFIG_PATH doesn't exist → return 'unconfigured'."""
        config_file = tmp_path / "does_not_exist.yaml"
        monkeypatch.setattr("agent.config_util.CONFIG_PATH", config_file)

        assert get_active_backend() == "unconfigured"


# ── _deep_merge_defaults ───────────────────────────────────────────────────


class TestDeepMergeDefaults:
    def test_empty_dict_gets_all_minimal_fields(self) -> None:
        """Merging {} with _MINIMAL_CONFIG fills every required key."""
        config: dict = {}
        _deep_merge_defaults(config, _MINIMAL_CONFIG)

        assert "agent" in config
        assert config["agent"]["backend"] == "local"
        assert config["agent"]["tolerance_seconds"] == 1.0
        assert config["agent"]["max_rounds"] == 10
        assert config["agent"]["remote"]["provider"] == "dashscope"
        assert config["agent"]["local"]["provider"] == "ollama"
        assert config["backend"]["api_url"] == "http://localhost:8000/v1"

    def test_existing_backend_not_overridden(self) -> None:
        """Existing agent.backend: 'local' is preserved over default 'remote'."""
        config: dict = {"agent": {"backend": "local"}}
        _deep_merge_defaults(config, _MINIMAL_CONFIG)

        assert config["agent"]["backend"] == "local"
        # Other fields still get filled
        assert config["agent"]["tolerance_seconds"] == 1.0

    def test_existing_remote_model_not_overridden(self) -> None:
        """Existing agent.remote.model stays ('qwen-max' vs no model default)."""
        config: dict = {"agent": {"remote": {"model": "qwen-max"}}}
        _deep_merge_defaults(config, _MINIMAL_CONFIG)

        assert config["agent"]["remote"]["model"] == "qwen-max"
        # Other remote fields still filled
        assert config["agent"]["remote"]["provider"] == "dashscope"


# ── save_remote_model ──────────────────────────────────────────────────────


class TestSaveRemoteModel:
    def test_activate_true_sets_backend_to_remote(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """activate=True → config writes agent.backend: 'remote'."""
        config_file = tmp_path / "config.local.yaml"
        monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", config_file)

        save_remote_model("qwen-turbo", activate=True)

        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["agent"]["backend"] == "remote"
        assert saved["agent"]["remote"]["model"] == "qwen-turbo"

    def test_activate_false_does_not_change_backend(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """activate=False → config preserves existing agent.backend."""
        config_file = tmp_path / "config.local.yaml"
        config_file.write_text("agent:\n  backend: local\n", encoding="utf-8")
        monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", config_file)

        save_remote_model("qwen-turbo", activate=False)

        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["agent"]["backend"] == "local"
        assert saved["agent"]["remote"]["model"] == "qwen-turbo"

    def test_file_not_exists_creates_with_full_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONFIG_PATH doesn't exist → creates file with full defaults + model."""
        config_file = tmp_path / "config.local.yaml"
        assert not config_file.exists()
        monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", config_file)

        save_remote_model("qwen-plus")

        assert config_file.exists()
        saved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert saved["agent"]["remote"]["model"] == "qwen-plus"
        assert "backend" not in saved["agent"]


# ── list_available_models ──────────────────────────────────────────────────


class TestListAvailableModels:
    def test_no_api_key_returns_auth_error(self) -> None:
        """api_key=None and get_api_key() returns None → auth_error."""
        with patch(
            "agent.config_util.get_api_key", return_value=None
        ) as mock_get_key:
            result = list_available_models(api_key=None)

        mock_get_key.assert_called_once()
        assert result["ok"] is False
        assert result["error_kind"] == "auth_error"
        assert result["models"] == []

    def test_timeout_returns_network_error(self) -> None:
        """requests.get raises Timeout → network_error."""
        with patch("agent.config_util.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()

            result = list_available_models(api_key="sk-test")

        assert result["ok"] is False
        assert result["error_kind"] == "network_error"

    def test_401_returns_auth_error(self) -> None:
        """requests.get returns 401 → auth_error (HTTPError path)."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "401 Unauthorized"
        )

        with patch("agent.config_util.requests.get", return_value=mock_resp):
            result = list_available_models(api_key="sk-test")

        assert result["ok"] is False
        assert result["error_kind"] == "auth_error"


def test_effective_config_precedence(tmp_path, monkeypatch):
    default = tmp_path / "config.yaml"
    local = tmp_path / "config.local.yaml"
    default.write_text("agent:\n  backend: remote\n  remote:\n    model: remote-default\n", encoding="utf-8")
    local.write_text("agent:\n  backend: local\n  local:\n    model: local-persisted\n", encoding="utf-8")
    monkeypatch.setattr("agent.config_util.CONFIG_PATH", default)
    monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", local)
    set_session_overrides(backend="local", model="session-model")
    config = load_config()
    assert config["agent"]["backend"] == "local"
    assert config["agent"]["local"]["model"] == "session-model"
    assert config["agent"]["remote"]["model"] == "remote-default"


def test_save_active_config_only_writes_ignored_local_file(tmp_path, monkeypatch):
    tracked = tmp_path / "config.yaml"
    tracked.write_text("agent:\n  backend: local\n", encoding="utf-8")
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("agent.config_util.CONFIG_PATH", tracked)
    monkeypatch.setattr("agent.config_util.LOCAL_CONFIG_PATH", local)
    before = tracked.read_text(encoding="utf-8")
    save_active_config("local", "tensile-qwen35:9b", reasoning_effort="none")
    assert tracked.read_text(encoding="utf-8") == before
    assert yaml.safe_load(local.read_text(encoding="utf-8"))["agent"]["local"]["model"] == "tensile-qwen35:9b"


def test_list_local_models_parses_ollama_tags():
    response = MagicMock()
    response.json.return_value = {"models": [{"name": "qwen3:8b", "digest": "d1", "size": 123}]}
    with patch("agent.config_util.requests.get", return_value=response):
        result = list_local_models()
    assert result["ok"] is True
    assert result["models"][0]["id"] == "qwen3:8b"


def test_local_model_digest_requires_exact_ollama_id():
    result = {
        "ok": True,
        "models": [
            {"id": "qwen3:8b", "digest": "official"},
            {"id": "qwen3:14b", "digest": "other"},
        ],
    }
    with patch("agent.config_util.list_local_models", return_value=result):
        assert get_local_model_digest("qwen3:8b") == "official"
        assert get_local_model_digest("qwen3") is None
