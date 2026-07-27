"""Agent LLM backends with a unified Native Function Calling interface.

The abstraction intentionally does **not** introduce MCP or any external protocol.
See ``docs/PROJECT_PLAN.md`` for the authoritative Agent-side design.
"""

from __future__ import annotations

import logging
import os
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from types import SimpleNamespace

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


class DeterministicPlanner(BaseAgentLLM):
    """Acceptance-only planner driven by validated history and interval state.

    The planner proposes tools but cannot approve its own conclusions:
    ``IterativeAgent`` still owns forced ranges, evidence thresholds,
    termination, projection, and all fail-closed checks.
    """

    def __init__(self, model: str = "v4.1-interval-policy-v1") -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        return f"deterministic/{self._model}"

    @staticmethod
    def _tool_call(name: str, arguments: dict[str, Any]) -> Any:
        function = SimpleNamespace(
            name=name,
            arguments=json.dumps(arguments, ensure_ascii=False),
        )
        call = SimpleNamespace(
            id=f"deterministic-{uuid.uuid4()}",
            function=function,
        )
        message = SimpleNamespace(
            content="deterministic acceptance policy",
            tool_calls=[call],
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @staticmethod
    def _history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") != "tool":
                continue
            try:
                payload = json.loads(str(message.get("content", "")))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "model_output" in payload:
                history.append(payload)
        return history

    @staticmethod
    def _candidate(messages: list[dict[str, Any]]) -> list[float]:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            match = re.search(
                r"当前候选区间:\s*\[([0-9.eE+-]+),\s*([0-9.eE+-]+)\]",
                str(message.get("content", "")),
            )
            if match:
                return [float(match.group(1)), float(match.group(2))]
        return [0.0, 1.0]

    @staticmethod
    def _same_range(left: Any, right: Any) -> bool:
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right) == 2
            and abs(float(left[0]) - float(right[0])) <= 1e-6
            and abs(float(left[1]) - float(right[1])) <= 1e-6
        )

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        del tools, temperature, max_tokens
        history = self._history(messages)
        valid = [item for item in history if item.get("ok") is True]
        is_v2 = self._model == "v2-interval-policy-v1"

        if len(valid) >= 2:
            current = valid[-1]
            previous = valid[-2]
            current_output = current.get("model_output") or {}
            previous_output = previous.get("model_output") or {}
            special = (
                current_output.get("type")
                if is_v2
                else current_output.get("special_case")
            )
            if (
                special in {"未夹紧", "视频异常"}
                and (
                    previous_output.get("type")
                    if is_v2
                    else previous_output.get("special_case")
                )
                == special
                and self._same_range(
                    current.get("sample_range"),
                    previous.get("sample_range"),
                )
            ):
                return self._tool_call(
                    "terminate",
                    {
                        "status": "unrecognized",
                        "unrecognized_reason": (
                            "not_clamped" if special == "未夹紧" else "video_anomaly"
                        ),
                    },
                )
            if not is_v2 and (
                current_output.get("clip_state") == "无法判断"
                and previous_output.get("clip_state") == "无法判断"
                and self._same_range(
                    current.get("sample_range"),
                    previous.get("sample_range"),
                )
            ):
                return self._tool_call(
                    "terminate",
                    {
                        "status": "unrecognized",
                        "unrecognized_reason": "visual_indeterminate",
                    },
                )

        # The program owns five fixed coverage windows. A mere count can be
        # polluted by earlier search negatives, so only propose no-fracture
        # when the latest five successful rounds are all strict negatives.
        if len(valid) >= 6 and all(
            (
                (
                    (item.get("model_output") or {}).get("has_fracture")
                    is False
                    and (item.get("model_output") or {}).get("type")
                    == "未断裂"
                )
                if is_v2
                else (item.get("model_output") or {}).get("clip_state")
                == "未断裂"
            )
            for item in valid[-5:]
        ):
            return self._tool_call("terminate", {"status": "no_fracture"})

        positive_indices = [
            index
            for index, item in enumerate(history)
            if (
                (item.get("model_output") or {}).get("has_fracture") is True
                if is_v2
                else (item.get("model_output") or {}).get("clip_state")
                in {"发生断裂", "已断裂"}
            )
        ]
        localized = [
            index
            for index in positive_indices
            if isinstance(history[index].get("inferred_time_range"), list)
        ]
        if len(positive_indices) >= 2 and len(localized) >= 2:
            ranges = [history[index]["inferred_time_range"] for index in localized]
            start = max(float(item[0]) for item in ranges)
            end = min(float(item[1]) for item in ranges)
            if start < end and end - start <= 1.0 + 1e-9:
                outputs = [history[index].get("model_output") or {} for index in positive_indices]
                mechanism = next(
                    (
                        (
                            output.get("type")
                            if is_v2
                            else output.get("fracture_mechanism")
                        )
                        for output in reversed(outputs)
                        if (
                            output.get("type")
                            if is_v2
                            else output.get("fracture_mechanism")
                        )
                    ),
                    None,
                )
                site = next(
                    (
                        (
                            output.get("location")
                            if is_v2
                            else output.get("fracture_site")
                        )
                        for output in reversed(outputs)
                        if (
                            output.get("location")
                            if is_v2
                            else output.get("fracture_site")
                        )
                    ),
                    None,
                )
                return self._tool_call(
                    "terminate",
                    {
                        "status": "fracture",
                        "fracture_type": mechanism,
                        "location": site,
                        "evidence_rounds": positive_indices,
                    },
                )

        start, end = self._candidate(messages)
        width = end - start
        if width > 1.0:
            margin = width * 0.25
            sample_range = [start + margin, end - margin]
        else:
            sample_range = [start, end]
        return self._tool_call(
            "sample_and_infer",
            {"sample_range": sample_range, "task_mode": "analyze"},
        )


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
        selected_cfg = (
            agent_cfg.get(backend, {})
            if backend in {"local", "remote", "deterministic"}
            else {}
        )
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

        if backend == "deterministic":
            deterministic_cfg = agent_cfg.get("deterministic", {})
            return DeterministicPlanner(
                model=deterministic_cfg.get("model", "v4.1-interval-policy-v1")
            )

        raise ValueError(
            f"Unsupported backend: {backend}. Use 'remote', 'local', or 'deterministic'."
        )
