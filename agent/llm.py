"""Agent LLM backends with a unified Native Function Calling interface.

The abstraction intentionally does **not** introduce MCP or any external protocol.
See ``docs/IMPLEMENTATIONS/model-agent-contract.md`` section 3.1 for the authoritative design.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from agent.config_util import get_api_key as _get_api_key
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None


class BaseAgentLLM(ABC):
    """Unified interface for the Meta-Agent LLM backend."""

    @abstractmethod
    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        """Call the model with Native Function Calling support.

        Args:
            messages: OpenAI-compatible message list.
            tools: OpenAI-compatible tool schema list.
            temperature: Sampling temperature.
            max_tokens: Optional maximum number of generated tokens.

        Returns:
            An OpenAI-compatible ChatCompletion object exposing
            ``choices[0].message.content`` and
            ``choices[0].message.tool_calls``.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the current model identifier for logging."""
        ...


class RemoteAPIClient(BaseAgentLLM):
    """Remote OpenAI-compatible API client (e.g. DashScope, SiliconFlow, OpenAI).

    The provider string is only used for log identifiers; the actual model name
    is passed through transparently.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        provider: str = "custom",
    ) -> None:
        self._model = model
        self._provider = provider
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "RemoteAPIClient requires the 'openai' package. "
                "Install it or set INFERENCE_MOCK=1 for testing."
            )
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return self.client.chat.completions.create(**kwargs)

    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"


class LocalClient(BaseAgentLLM):
    """Local OpenAI-compatible endpoint client (e.g. Ollama, vLLM, llama.cpp).

    The provider string is only used for log identifiers; the actual model name
    is passed through transparently.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        provider: str = "ollama",
    ) -> None:
        self._model = model
        self._provider = provider
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "LocalClient requires the 'openai' package. "
                "Install it or set INFERENCE_MOCK=1 for testing."
            )
        self.client = OpenAI(api_key="EMPTY", base_url=base_url)

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return self.client.chat.completions.create(**kwargs)

    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"


class AgentLLMFactory:
    """Create the appropriate Agent LLM client from a configuration dict."""

    @staticmethod
    def create(config: dict[str, Any]) -> BaseAgentLLM:
        """Instantiate a ``BaseAgentLLM`` subclass from ``config``.

        Expected configuration layout (matching ``agent/config.yaml``):

        .. code-block:: yaml

            agent:
              backend: "remote"  # or "local"
              remote:
                provider: "dashscope"
                model: "qwen2.5-14b-instruct"
                base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
                api_key: null      # or env var LLM_API_KEY
              local:
                provider: "ollama"
                model: "qwen2.5:7b"
                base_url: "http://localhost:11434/v1"
        """
        agent_cfg = config.get("agent", {})
        backend = agent_cfg.get("backend", "remote")

        if backend == "remote":
            remote_cfg = agent_cfg.get("remote", {})
            api_key = remote_cfg.get("api_key") or _get_api_key()
            if not api_key:
                raise ValueError(
                    "Remote backend requires 'api_key' in config or "
                    "LLM_API_KEY environment variable"
                )
            base_url = remote_cfg.get("base_url")
            if not base_url:
                raise ValueError("Remote backend requires 'base_url'")
            return RemoteAPIClient(
                model=remote_cfg["model"],
                api_key=api_key,
                base_url=base_url,
                provider=remote_cfg.get("provider", "custom"),
            )

        if backend == "local":
            local_cfg = agent_cfg.get("local", {})
            return LocalClient(
                model=local_cfg["model"],
                base_url=local_cfg.get("base_url", "http://localhost:11434/v1"),
                provider=local_cfg.get("provider", "ollama"),
            )

        raise ValueError(
            f"Unsupported backend: {backend}. Use 'remote' or 'local'."
        )
