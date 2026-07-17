"""Agent LLM backends with a unified Native Function Calling interface.

The abstraction intentionally does **not** introduce MCP or any external protocol.
See ``docs/PROJECT_PLAN.md`` for the authoritative Agent-side design.
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod

from agent.config_util import get_api_key as _get_api_key
from agent.config_util import get_local_model_digest, list_local_models
from agent.llm_trace import TransportTraceRecorder
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None


logger = logging.getLogger(__name__)


def _record_trace(recorder: TransportTraceRecorder | None, **kwargs: Any) -> None:
    if recorder is None:
        return
    try:
        recorder.write(**kwargs)
    except Exception:
        logger.exception("Failed to persist decision-model transport trace")


class BaseAgentLLM(ABC):
    """Unified interface for the TensileAgent LLM backend."""

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


class LocalBackendUnavailable(RuntimeError):
    """The configured local model service cannot be reached."""


class LocalModelMissing(RuntimeError):
    """The configured model is not installed in the local service."""


class LocalModelDigestMismatch(RuntimeError):
    """The local model alias changed after a task pinned its digest."""


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
        trace_recorder: TransportTraceRecorder | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._trace_recorder = trace_recorder
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "RemoteAPIClient requires the 'openai' package. "
                "Install it or set INFERENCE_MOCK=1 for testing."
            )
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)

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
        started_at = time.monotonic()
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            _record_trace(self._trace_recorder, request=kwargs, response=None, started_at=started_at, error=exc)
            raise
        _record_trace(self._trace_recorder, request=kwargs, response=response, started_at=started_at)
        return response

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
        reasoning_effort: str = "none",
        trace_recorder: TransportTraceRecorder | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._reasoning_effort = reasoning_effort
        self._trace_recorder = trace_recorder
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "LocalClient requires the 'openai' package. "
                "Install it or set INFERENCE_MOCK=1 for testing."
            )
        self.client = OpenAI(api_key="EMPTY", base_url=base_url, max_retries=0)

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
        kwargs["reasoning_effort"] = self._reasoning_effort
        started_at = time.monotonic()
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            _record_trace(self._trace_recorder, request=kwargs, response=None, started_at=started_at, error=exc)
            raise
        _record_trace(
            self._trace_recorder,
            request=kwargs,
            response=response,
            started_at=started_at,
            include_reasoning=self._reasoning_effort != "none",
        )
        return response

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
        selected_cfg = agent_cfg.get(backend, {}) if backend in {"local", "remote"} else {}
        runtime_cfg = config.get("_runtime", {})
        trace_recorder = None
        task_id = runtime_cfg.get("task_id")
        trace_root = runtime_cfg.get("llm_trace_root")
        if task_id and trace_root:
            digest = runtime_cfg.get("model_digest")
            if backend == "local" and not digest and selected_cfg.get("model"):
                digest = get_local_model_digest(
                    selected_cfg["model"], selected_cfg.get("base_url", "http://localhost:11434/v1")
                )
            trace_recorder = TransportTraceRecorder(
                trace_root,
                str(task_id),
                {
                    "backend": backend,
                    "provider": selected_cfg.get("provider"),
                    "model": selected_cfg.get("model"),
                    "digest": digest,
                    "base_url": selected_cfg.get("base_url"),
                    "reasoning_effort": selected_cfg.get("reasoning_effort", "none"),
                },
            )

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
                trace_recorder=trace_recorder,
            )

        if backend == "local":
            local_cfg = agent_cfg.get("local", {})
            local_status = list_local_models(local_cfg.get("base_url", "http://localhost:11434/v1"))
            if not local_status.get("ok"):
                raise LocalBackendUnavailable(local_status.get("warning", "Ollama 不可用"))
            installed = {
                item.get("id"): item.get("digest")
                for item in local_status.get("models", [])
                if item.get("id")
            }
            selected_model = local_cfg.get("model")
            if selected_model not in installed:
                raise LocalModelMissing(f"本地模型未安装: {local_cfg.get('model')}")
            expected_digest = runtime_cfg.get("model_digest")
            actual_digest = installed.get(selected_model)
            if expected_digest and actual_digest and expected_digest != actual_digest:
                raise LocalModelDigestMismatch(
                    f"本地模型 digest 已变更: {selected_model}；请重新创建任务"
                )
            return LocalClient(
                model=local_cfg["model"],
                base_url=local_cfg.get("base_url", "http://localhost:11434/v1"),
                provider=local_cfg.get("provider", "ollama"),
                reasoning_effort=local_cfg.get("reasoning_effort", "none"),
                trace_recorder=trace_recorder,
            )

        raise ValueError(
            f"Unsupported backend: {backend}. Use 'remote' or 'local'."
        )
