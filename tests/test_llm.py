from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent.llm import AgentLLMFactory, BaseAgentLLM, LocalClient, RemoteAPIClient


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
        self._calls.append(((messages, tools), {"temperature": temperature, "max_tokens": max_tokens}))
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
    with patch("agent.llm.OpenAI") as mock_openai:
        client = AgentLLMFactory.create(config)
        assert isinstance(client, LocalClient)
        assert client.model_name == "ollama/qwen2.5:7b"
        mock_openai.assert_called_once_with(api_key="EMPTY", base_url="http://localhost:11434/v1")


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
