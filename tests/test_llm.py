from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent.llm import (
    DeterministicPlanner,
    AgentLLMFactory,
    BaseAgentLLM,
    LocalBackendUnavailable,
    LocalClient,
    LocalModelDigestMismatch,
    LocalModelMissing,
    RemoteAPIClient,
)


class DummyLLM(BaseAgentLLM):
    """In-memory LLM for unit tests."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = responses or []
        self._calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._idx = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        self._calls.append(
            ((messages, tools), {"temperature": temperature, "max_tokens": max_tokens})
        )
        resp = self._responses[self._idx]
        self._idx = min(self._idx + 1, len(self._responses) - 1)
        return resp

    @property
    def model_name(self) -> str:
        return "dummy/test"


def make_tool_response(name: str, arguments: dict[str, Any], content: str = "") -> Any:
    """Return a minimal OpenAI-compatible completion object with one tool_call."""
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.type = "function"
    tool_call.function.name = name
    tool_call.function.arguments = __import__("json").dumps(arguments)

    message = MagicMock()
    message.content = content
    message.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def test_factory_creates_remote_client_with_env_api_key():
    config = {
        "agent": {
            "backend": "remote",
            "remote": {
                "provider": "dashscope",
                "model": "qwen2.5-14b-instruct",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": None,
            },
        }
    }
    with patch.dict("os.environ", {"LLM_API_KEY": "sk-test"}):
        with patch("agent.llm.OpenAI") as mock_openai:
            client = AgentLLMFactory.create(config)
            assert isinstance(client, RemoteAPIClient)
            assert client.model_name == "dashscope/qwen2.5-14b-instruct"
            mock_openai.assert_called_once_with(
                api_key="sk-test",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                max_retries=0,
                timeout=300.0,
            )


def test_factory_creates_local_client():
    config = {
        "agent": {
            "backend": "local",
            "local": {
                "provider": "ollama",
                "model": "qwen2.5:7b",
                "base_url": "http://localhost:11434/v1",
            },
        }
    }
    with (
        patch(
            "agent.llm.list_local_models",
            return_value={"ok": True, "models": [{"id": "qwen2.5:7b"}]},
        ),
        patch("agent.llm.OpenAI") as mock_openai,
    ):
        client = AgentLLMFactory.create(config)
        assert isinstance(client, LocalClient)
        assert client.model_name == "ollama/qwen2.5:7b"
        mock_openai.assert_called_once_with(
            api_key="EMPTY",
            base_url="http://localhost:11434/v1",
            max_retries=0,
            timeout=300.0,
        )


def test_factory_rejects_changed_pinned_local_digest():
    config = {
        "agent": {
            "backend": "local",
            "local": {
                "provider": "ollama",
                "model": "tensile-qwen35:9b",
                "base_url": "http://localhost:11434/v1",
            },
        },
        "_runtime": {"model_digest": "old-digest"},
    }
    with (
        patch(
            "agent.llm.list_local_models",
            return_value={
                "ok": True,
                "models": [{"id": "tensile-qwen35:9b", "digest": "new-digest"}],
            },
        ),
        pytest.raises(LocalModelDigestMismatch, match="digest"),
    ):
        AgentLLMFactory.create(config)


@patch("agent.llm._get_api_key", return_value=None)
@patch.dict("os.environ", {}, clear=True)
def test_factory_rejects_missing_remote_api_key(mock_get_key):
    config = {
        "agent": {
            "backend": "remote",
            "remote": {
                "model": "qwen2.5-14b-instruct",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": None,
            },
        }
    }
    with pytest.raises(ValueError, match="Remote backend requires"):
        AgentLLMFactory.create(config)


def test_factory_rejects_unknown_backend():
    config = {"agent": {"backend": "on-prem"}}
    with pytest.raises(ValueError, match="Unsupported backend"):
        AgentLLMFactory.create(config)


def test_factory_fails_closed_when_ollama_is_offline():
    config = {
        "agent": {
            "backend": "local",
            "local": {"model": "qwen3:8b", "base_url": "http://localhost:11434/v1"},
        }
    }
    with patch(
        "agent.llm.list_local_models", return_value={"ok": False, "warning": "offline"}
    ):
        with pytest.raises(LocalBackendUnavailable, match="offline"):
            AgentLLMFactory.create(config)


def test_factory_fails_closed_when_local_model_is_missing():
    config = {
        "agent": {
            "backend": "local",
            "local": {"model": "qwen3:8b", "base_url": "http://localhost:11434/v1"},
        }
    }
    with patch("agent.llm.list_local_models", return_value={"ok": True, "models": []}):
        with pytest.raises(LocalModelMissing, match="qwen3:8b"):
            AgentLLMFactory.create(config)


def test_local_client_disables_reasoning_by_default():
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        client = LocalClient(model="qwen3:8b")
        client.chat_with_tools(messages=[{"role": "user", "content": "hi"}], tools=[])
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["reasoning_effort"] == "none"


def test_remote_client_passes_max_tokens():
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
            temperature=0.5,
            max_tokens=100,
        )
        mock_client.chat.completions.create.assert_called_once_with(
            model="qwen-test",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
            tool_choice="auto",
            temperature=0.5,
            max_tokens=100,
        )


def test_remote_client_retries_on_retryable_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class RetryableError(Exception):
            status_code = 500

        success = make_tool_response("sample_and_infer", {"sample_range": [0, 1]})
        mock_client.chat.completions.create.side_effect = [
            RetryableError("server boom"),
            success,
        ]
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        response = client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        assert response is success
        assert mock_client.chat.completions.create.call_count == 2


def test_remote_client_retries_exhausted_raises_last_error(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class RetryableError(Exception):
            status_code = 503

        mock_client.chat.completions.create.side_effect = [
            RetryableError("first"),
            RetryableError("second"),
            RetryableError("third"),
        ]
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        with pytest.raises(RetryableError, match="third"):
            client.chat_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "noop"}}],
            )
        assert mock_client.chat.completions.create.call_count == 3


def test_remote_client_does_not_retry_non_retryable_error(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class AuthError(Exception):
            status_code = 401

        mock_client.chat.completions.create.side_effect = AuthError("no permission")
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        with pytest.raises(AuthError, match="no permission"):
            client.chat_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "noop"}}],
            )
        assert mock_client.chat.completions.create.call_count == 1


def test_local_client_retries_on_retryable_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class RetryableError(Exception):
            status_code = 500

        success = make_tool_response("sample_and_infer", {"sample_range": [0, 1]})
        mock_client.chat.completions.create.side_effect = [
            RetryableError("server boom"),
            success,
        ]
        client = LocalClient(model="qwen-test")
        response = client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        assert response is success
        assert mock_client.chat.completions.create.call_count == 2


def test_remote_client_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class RateLimitError(Exception):
            status_code = 429

        success = make_tool_response("sample_and_infer", {"sample_range": [0, 1]})
        mock_client.chat.completions.create.side_effect = [
            RateLimitError("rate limited"),
            success,
        ]
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        response = client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        assert response is success
        assert mock_client.chat.completions.create.call_count == 2


def test_remote_client_retries_on_name_matched_network_error_then_succeeds(
    monkeypatch,
):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        success = make_tool_response("sample_and_infer", {"sample_range": [0, 1]})
        mock_client.chat.completions.create.side_effect = [
            ConnectionError("connection reset"),
            success,
        ]
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
        )
        response = client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        assert response is success
        assert mock_client.chat.completions.create.call_count == 2


def test_local_client_does_not_retry_non_retryable_4xx_error(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class AuthError(Exception):
            status_code = 401

        mock_client.chat.completions.create.side_effect = AuthError("no permission")
        client = LocalClient(model="qwen-test")
        with pytest.raises(AuthError, match="no permission"):
            client.chat_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "noop"}}],
            )
        assert mock_client.chat.completions.create.call_count == 1


def _planner_tool(response: Any) -> tuple[str, dict[str, Any]]:
    call = response.choices[0].message.tool_calls[0]
    return call.function.name, json.loads(call.function.arguments)


def test_factory_creates_acceptance_deterministic_planner():
    client = AgentLLMFactory.create(
        {
            "agent": {
                "backend": "deterministic",
                "deterministic": {"model": "v4.1-interval-policy-v1"},
            }
        }
    )
    assert isinstance(client, DeterministicPlanner)
    assert client.model_name == "deterministic/v4.1-interval-policy-v1"


def test_deterministic_planner_bisects_candidate_and_terminates_special_case():
    planner = DeterministicPlanner()
    messages = [
        {
            "role": "user",
            "content": "当前候选区间: [20.0, 80.0]\n请通过 tool_calls 输出你的下一步决策。",
        }
    ]
    name, arguments = _planner_tool(planner.chat_with_tools(messages, []))
    assert name == "sample_and_infer"
    assert arguments["sample_range"] == [35.0, 65.0]

    special = {
        "ok": True,
        "sample_range": [35.0, 65.0],
        "model_output": {
            "clip_state": "无法判断",
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": "未夹紧",
        },
    }
    messages.extend(
        [
            {"role": "tool", "content": json.dumps(special, ensure_ascii=False)},
            {"role": "tool", "content": json.dumps(special, ensure_ascii=False)},
        ]
    )
    name, arguments = _planner_tool(planner.chat_with_tools(messages, []))
    assert name == "terminate"
    assert arguments == {
        "status": "unrecognized",
        "unrecognized_reason": "not_clamped",
    }


def test_deterministic_planner_does_not_count_search_negatives_as_coverage():
    planner = DeterministicPlanner()
    outputs = ["未断裂"] * 5 + ["发生断裂", "未断裂"]
    messages = [
        {
            "role": "user",
            "content": "当前候选区间: [30.0, 40.0]\n请通过 tool_calls 输出你的下一步决策。",
        },
        *[
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        "ok": True,
                        "sample_range": [float(index), float(index + 1)],
                        "model_output": {
                            "clip_state": state,
                            "fracture_mechanism": None,
                            "fracture_site": None,
                            "special_case": None,
                        },
                        "inferred_time_range": (
                            [float(index), float(index + 1)]
                            if state == "发生断裂"
                            else None
                        ),
                    },
                    ensure_ascii=False,
                ),
            }
            for index, state in enumerate(outputs)
        ],
    ]
    name, _ = _planner_tool(planner.chat_with_tools(messages, []))
    assert name == "sample_and_infer"


def test_v2_deterministic_planner_terminates_special_case():
    planner = DeterministicPlanner("v2-interval-policy-v1")
    special = {
        "ok": True,
        "sample_range": [0.0, 10.0],
        "model_output": {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未夹紧",
            "location": None,
        },
    }
    messages = [
        {"role": "tool", "content": json.dumps(special, ensure_ascii=False)},
        {"role": "tool", "content": json.dumps(special, ensure_ascii=False)},
    ]
    name, arguments = _planner_tool(planner.chat_with_tools(messages, []))
    assert name == "terminate"
    assert arguments == {
        "status": "unrecognized",
        "unrecognized_reason": "not_clamped",
    }


def test_v2_deterministic_planner_terminates_localized_fracture():
    planner = DeterministicPlanner("v2-interval-policy-v1")
    messages = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "ok": True,
                    "sample_range": [1.0, 2.0],
                    "model_output": {
                        "has_fracture": True,
                        "fracture_between": [1, 2],
                        "type": "脆性断裂",
                        "location": "inside_gauge",
                    },
                    "inferred_time_range": [1.1, 1.8],
                },
                ensure_ascii=False,
            ),
        },
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "ok": True,
                    "sample_range": [1.2, 1.9],
                    "model_output": {
                        "has_fracture": True,
                        "fracture_between": [1, 2],
                        "type": "脆性断裂",
                        "location": "inside_gauge",
                    },
                    "inferred_time_range": [1.3, 1.7],
                },
                ensure_ascii=False,
            ),
        },
    ]
    name, arguments = _planner_tool(planner.chat_with_tools(messages, []))
    assert name == "terminate"
    assert arguments["status"] == "fracture"
    assert arguments["fracture_type"] == "脆性断裂"
    assert arguments["location"] == "inside_gauge"


def test_factory_passes_configured_llm_timeout_to_clients():
    """llm_timeout_seconds from config is forwarded to both client backends."""
    remote_config = {
        "agent": {
            "backend": "remote",
            "llm_timeout_seconds": 42.5,
            "remote": {
                "provider": "dashscope",
                "model": "qwen-test",
                "base_url": "https://example.com/v1",
                "api_key": "sk-test",
            },
        }
    }
    with patch("agent.llm.OpenAI") as mock_openai:
        AgentLLMFactory.create(remote_config)
        assert mock_openai.call_args.kwargs["timeout"] == 42.5

    local_config = {
        "agent": {
            "backend": "local",
            "llm_timeout_seconds": 120.0,
            "local": {
                "provider": "ollama",
                "model": "qwen-test",
                "base_url": "http://localhost:11434/v1",
            },
        }
    }
    with (
        patch(
            "agent.llm.list_local_models",
            return_value={"ok": True, "models": [{"id": "qwen-test"}]},
        ),
        patch("agent.llm.OpenAI") as mock_openai,
    ):
        AgentLLMFactory.create(local_config)
        assert mock_openai.call_args.kwargs["timeout"] == 120.0


def test_remote_client_timeout_is_retryable(monkeypatch):
    """OpenAI read timeout is classified as retryable by _is_retryable_error."""
    monkeypatch.setattr("agent.llm.time.sleep", lambda _s: None)
    with patch("agent.llm.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        class FakeTimeoutError(Exception):
            status_code = None

        success = make_tool_response("sample_and_infer", {"sample_range": [0, 1]})
        mock_client.chat.completions.create.side_effect = [
            FakeTimeoutError("timed out"),
            success,
        ]
        client = RemoteAPIClient(
            model="qwen-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider="test",
            timeout=30.0,
        )
        response = client.chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "noop"}}],
        )
        assert response is success
        assert mock_client.chat.completions.create.call_count == 2
