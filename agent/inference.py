"""Concrete inference client for the fine-tuned MiniCPM-V model.

The default implementation talks to an OpenAI-compatible LLaMA-Factory
endpoint.  It encodes the temporary MP4 clip as a Base64 ``data:video/mp4``
URL so that no local path is sent to the model service.
"""

from __future__ import annotations

import base64
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from agent.parser import ParseError, ResultParser
from agent.prompts import SYSTEM_PROMPT
from agent.sampling import ClipBuildResult
from agent.schema import SampleAndInferDiagnostics, ValidationErrorInfo

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    OpenAI = None

try:
    import httpx

    _DEFAULT_TIMEOUT: Any = httpx.Timeout(connect=10.0, read=300.0)
except Exception:  # pragma: no cover - httpx is a transitive dep of openai
    _DEFAULT_TIMEOUT = 300.0


logger = logging.getLogger(__name__)

DEFAULT_MAX_REQUEST_SIZE = 32 * 1024 * 1024  # 32 MiB
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 2.0
DEFAULT_MIME_TYPE = "video/mp4"


@dataclass
class InferenceResult:
    """Public result of a single inference attempt.

    The envelope separates a successful model output from an invalid model
    output (with a stable parser error code) and transport failures, which
    are raised as exceptions instead of being returned.

    ``preprocessing`` carries the server-side ``preprocessing`` metadata
    (frame table / processor info) when the server adapter is installed.
    ``None`` means the required server metadata was absent. The caller must
    fail closed instead of guessing a frame mapping locally.
    """

    ok: bool
    model_output: dict[str, Any] | None = None
    error: ParseError | None = None
    attempts: int = 1
    preprocessing: dict[str, Any] | None = None
    diagnostics: SampleAndInferDiagnostics | None = None


@runtime_checkable
class InferenceClient(Protocol):
    """Protocol for clients that call the fine-tuned MiniCPM-V model."""

    def infer(
        self, video_input: str | ClipBuildResult, prompt: str
    ) -> InferenceResult:
        """Run inference on ``video_input`` with ``prompt``.

        ``video_input`` may be a local temporary MP4 path or a
        ``ClipBuildResult`` produced by ``FfmpegVideoClipBuilder``.  When a
        ``ClipBuildResult`` is supplied, its ``manifest`` is forwarded as
        internal preprocessing metadata for diagnostics.

        Returns an ``InferenceResult``.  Transport and configuration failures
        are raised as exceptions; an invalid model output is returned with
        ``ok=False`` and a structured parser error.
        """
        ...


def _resolve_video_input(
    video_input: str | ClipBuildResult,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Return the file path and optional manifest from ``video_input``."""
    if isinstance(video_input, ClipBuildResult):
        return video_input.path, video_input.manifest
    return str(video_input), None


def _is_retryable_error(exc: Exception) -> bool:
    """Return whether ``exc`` warrants a transport retry.

    Retryable: HTTP 5xx, HTTP 429, connection/timeout/network errors and
    the equivalent OpenAI client exception types.  Deterministic client
    errors (4xx other than 429) are not retried.
    """
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code >= 500 or status_code == 429

    name = type(exc).__name__
    if any(
        keyword in name
        for keyword in (
            "ConnectionError",
            "TimeoutError",
            "ConnectError",
            "ReadTimeout",
            "NetworkError",
        )
    ):
        return True

    if OpenAI is not None:
        try:
            from openai import (
                APIConnectionError,
                APITimeoutError,
                InternalServerError,
                RateLimitError,
            )

            return isinstance(
                exc,
                (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError),
            )
        except Exception:  # pragma: no cover - defensive
            pass

    return False


def _is_mp4_file(path: str) -> bool:
    """Check extension and ISO BMFF magic signature for an MP4 file."""
    ext = os.path.splitext(path)[1].lower()
    if ext != ".mp4":
        return False

    with open(path, "rb") as f:
        header = f.read(16)
    if len(header) < 8:
        return False

    # ISO base media file format: bytes 4-7 are "ftyp".
    if header[4:8] != b"ftyp":
        return False

    brands = {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"M4A ", b"3gp5"}
    return any(brand in header for brand in brands)


def _encode_video_to_data_url(path: str) -> str:
    """Read an MP4 file and return a Base64 ``data:video/mp4`` URL."""
    with open(path, "rb") as f:
        raw = f.read()
    payload = base64.b64encode(raw).decode("ascii")
    return f"data:{DEFAULT_MIME_TYPE};base64,{payload}"


def _redact_data_url(url: str) -> str:
    """Return a log-safe preview of a Base64 data URL.

    Any non-empty Base64 payload is removed completely; diagnostics retain
    only the media prefix and payload length.
    """
    if not url or not url.startswith("data:"):
        return url
    prefix, sep, payload = url.partition(",")
    if not sep or not payload:
        return url
    return f"{prefix},[REDACTED:{len(payload)} chars]"


def _redact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deep copy of ``messages`` with Base64 video URLs redacted."""
    redacted: list[dict[str, Any]] = []
    for msg in messages:
        copy: dict[str, Any] = dict(msg)
        content = copy.get("content")
        if isinstance(content, list):
            new_content: list[dict[str, Any]] = []
            for item in content:
                new_item: dict[str, Any] = dict(item)
                if item.get("type") == "video_url":
                    url = item.get("video_url", {}).get("url", "")
                    new_item["video_url"] = {"url": _redact_data_url(url)}
                new_content.append(new_item)
            copy["content"] = new_content
        redacted.append(copy)
    return redacted


def _redact_dict_values(obj: Any) -> Any:
    """Recursively redact Base64 data URLs in string values of a dict/list."""
    if isinstance(obj, dict):
        return {k: _redact_dict_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_dict_values(v) for v in obj]
    if isinstance(obj, str):
        if obj.startswith("data:") and "," in obj:
            return _redact_data_url(obj)
        return obj
    return obj


def _extract_preprocessing_from_response(response: Any) -> dict[str, Any] | None:
    """Extract the ``preprocessing`` field from an OpenAI ``ChatCompletion`` response.

    The server adapter injects ``preprocessing`` at the top level of the JSON
    response.  Because the OpenAI Pydantic model typically ignores unknown
    fields, we try several access paths in order:

    1. ``response.model_dump()`` -- includes the field if the model config
       permits extra fields.
    2. ``response.model_extra`` -- Pydantic v2 bucket for unrecognised keys.
    3. Top-level attribute access (for monkey-patched or proxy objects).

    Returns the dict value or ``None`` when the field is absent.
    """
    # Path 1: model_dump() includes extra fields when extra='allow'.
    try:
        dump: dict[str, Any] = response.model_dump()
        pp = dump.get("preprocessing")
        if pp is not None:
            return pp
    except Exception:
        pass

    # Path 2: model_extra (Pydantic v2, available even with extra='ignore').
    try:
        extra: dict[str, Any] = getattr(response, "model_extra", None) or {}
        pp = extra.get("preprocessing")
        if pp is not None:
            return pp
    except Exception:
        pass

    # Path 3: direct attribute (covers test mocks / dict-like objects).
    try:
        pp = getattr(response, "preprocessing", None)
        if pp is not None:
            return pp
    except Exception:
        pass

    return None


def _validate_preprocessing_meta(meta: dict[str, Any] | None) -> str | None:
    """Validate server-returned ``preprocessing`` metadata.

    Returns ``None`` when the metadata is valid, or an error-code string
    describing the first violation.

    The metadata is part of the runtime contract, not optional diagnostics.
    """
    if meta is None:
        return "missing_or_invalid_preprocessing_metadata"

    request_id = meta.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        return "missing_or_invalid_request_id"

    processor_version = meta.get("processor_version")
    if (
        not isinstance(processor_version, str)
        or not processor_version.strip()
        or processor_version.strip().lower() == "unknown"
    ):
        return "missing_or_invalid_processor_version"

    max_frames = meta.get("max_frames")
    if not isinstance(max_frames, int) or max_frames <= 0:
        return "max_frames_not_positive_integer"
    if max_frames != 8:
        return "max_frames_not_8"

    frames = meta.get("frames")
    if not isinstance(frames, list) or not frames:
        return "missing_or_invalid_frames"
    if len(frames) > 8:
        logger.warning(
            "Preprocessing frames count %d exceeds max_frames %d",
            len(frames), max_frames,
        )
        return "too_many_frames"

    # Check monotonic and continuous indices (0, 1, 2, ...).
    for i, entry in enumerate(frames):
        if not isinstance(entry, dict):
            return "missing_or_invalid_frames"
        idx = entry.get("index")
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            logger.warning(
                "Preprocessing frame[%d] has invalid index: %r", i, idx
            )
            return "non_monotonic_indices"

        timestamp = entry.get("timestamp")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
        ):
            return "invalid_frame_timestamp"
        if i > 0 and timestamp <= frames[i - 1]["timestamp"]:
            return "non_monotonic_timestamps"
        if idx != i:
            logger.warning(
                "Preprocessing frame[%d] index %d is not expected %d",
                i, idx, i,
            )
            return "non_monotonic_indices"

    deployment = meta.get("deployment_manifest")
    required_deployment = {
        "model_version",
        "transformers_version",
        "llamafactory_version",
        "base_model_version",
        "artifact_version",
        "config_fingerprint",
        "runtime_device",
        "runtime_dtype",
    }
    if not isinstance(deployment, dict) or any(
        not isinstance(deployment.get(key), str) or not deployment[key].strip()
        for key in required_deployment
    ):
        return "missing_or_invalid_deployment_manifest"

    return None


class LlamaFactoryInferenceClient:
    """OpenAI-compatible client that sends Base64 MP4 video to the model."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "EMPTY",
        system_prompt: str = SYSTEM_PROMPT,
        max_request_size: int = DEFAULT_MAX_REQUEST_SIZE,
        timeout: Any = _DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.max_request_size = max_request_size
        self.timeout = timeout
        self.max_retries = max_retries
        if OpenAI is None:  # pragma: no cover - dependency guard
            raise ModuleNotFoundError(
                "LlamaFactoryInferenceClient requires the 'openai' package. "
                "Install it or use a mock InferenceClient for testing."
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # transport retry is handled explicitly below
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(model={self.model!r}, "
            f"base_url={self.base_url!r}, api_key=***REDACTED***)"
        )

    def infer(
        self, video_input: str | ClipBuildResult, prompt: str
    ) -> InferenceResult:
        """Call the model and return the parsed JSON output plus diagnostics."""
        video_path, manifest = _resolve_video_input(video_input)

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Inference video not found: {video_path}")
        if not _is_mp4_file(video_path):
            raise ValueError(f"Invalid or non-MP4 video file: {video_path}")

        data_url = _encode_video_to_data_url(video_path)
        if len(data_url) > self.max_request_size:
            raise RuntimeError(
                f"Base64 video payload ({len(data_url)} chars) exceeds "
                f"max_request_size ({self.max_request_size} bytes)"
            )

        base64_payload = data_url.split(",", 1)[1] if "," in data_url else ""

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]

        extra_body: dict[str, Any] | None = None
        if manifest is not None:
            extra_body = {"preprocessing": {"temp_video_manifest": manifest}}

        logger.info(
            "Sending inference request model=%s base_url=%s video_path=%s "
            "payload_chars=%d manifest_frames=%d",
            self.model,
            self.base_url,
            video_path,
            len(data_url),
            len(manifest) if manifest else 0,
        )

        transport_retries = 0

        def _call_model(
            current_messages: list[dict[str, Any]],
        ) -> Any:
            """Execute one model-output attempt, with transport retries."""
            nonlocal transport_retries
            last_error: Exception | None = None
            for attempt in range(self.max_retries + 1):
                try:
                    kwargs: dict[str, Any] = {
                        "model": self.model,
                        "messages": current_messages,
                        "temperature": 0.2,
                        "max_tokens": 512,
                    }
                    if extra_body is not None:
                        kwargs["extra_body"] = extra_body
                    return self.client.chat.completions.create(**kwargs)
                except Exception as exc:
                    last_error = exc
                    if attempt >= self.max_retries or not _is_retryable_error(exc):
                        raise
                    transport_retries += 1
                    sleep_seconds = DEFAULT_RETRY_BACKOFF ** attempt
                    logger.warning(
                        "Inference transport retryable error on attempt %d: %s. "
                        "Retrying in %.1fs",
                        attempt + 1,
                        exc,
                        sleep_seconds,
                    )
                    time.sleep(sleep_seconds)

            # Defensive: should only happen if the retry loop exits without
            # either succeeding or raising, which is impossible with the
            # current logic but kept for type safety.
            raise last_error  # type: ignore[misc]

        # Capture the last raw HTTP response for preprocessing extraction.
        _last_raw_response: list[Any] = [None]
        _last_assistant_content: list[str | None] = [None]

        def _fetch_fn(last_error: ParseError | None) -> str:
            nonlocal messages
            if last_error is not None:
                correction = (
                    f"Your previous response failed validation ({last_error.code}): "
                    f"{last_error.message}. Output only the complete valid JSON "
                    "object with exactly the five required fields and no Markdown "
                    "fences or surrounding text."
                )
                if _last_assistant_content[0] is not None:
                    messages = messages + [
                        {"role": "assistant", "content": _last_assistant_content[0]}
                    ]
                messages = messages + [{"role": "user", "content": correction}]
            response = _call_model(messages)
            _last_raw_response[0] = response
            content = response.choices[0].message.content or ""
            _last_assistant_content[0] = content
            return content

        infer_start = time.perf_counter()
        parse_result = ResultParser.parse_with_retries(_fetch_fn, max_retries=2)
        infer_elapsed = time.perf_counter() - infer_start

        # Extract server-side preprocessing metadata.
        # The raw dict (or None) is propagated to InferenceResult so that
        # the caller can decide whether to use server frames or local
        # manifest for fracture_between mapping.
        preprocessing: dict[str, Any] | None = None
        if _last_raw_response[0] is not None:
            raw_pp = _extract_preprocessing_from_response(_last_raw_response[0])
            if raw_pp is not None:
                err_code = _validate_preprocessing_meta(raw_pp)
                if err_code is None:
                    logger.info(
                        "Server preprocessing metadata OK: max_frames=%s, "
                        "frames=%d",
                        raw_pp.get("max_frames"),
                        len(raw_pp.get("frames", [])),
                    )
                else:
                    logger.warning(
                        "Server preprocessing metadata invalid (%s): %s",
                        err_code, raw_pp,
                    )
                # Always store the raw dict so caller can distinguish
                # "present but invalid" from "missing entirely".
                preprocessing = raw_pp
            else:
                logger.warning(
                    "No preprocessing metadata in inference response; the "
                    "runtime caller must fail closed."
                )

        # Build a redacted raw HTTP envelope for diagnostics.
        raw_response_dump: dict[str, Any] = {}
        response_id: str | None = None
        if _last_raw_response[0] is not None:
            try:
                raw_response_dump = _last_raw_response[0].model_dump()
            except Exception:
                pass
            try:
                extra = getattr(_last_raw_response[0], "model_extra", None) or {}
                raw_response_dump.update(extra)
            except Exception:
                pass
            response_id = raw_response_dump.get("id")

        raw_http_response: dict[str, Any] = {
            "request": {
                "model": self.model,
                "messages": _redact_messages(messages),
                "temperature": 0.2,
                "max_tokens": 512,
                "extra_body": extra_body,
            },
            "response": _redact_dict_values(raw_response_dump),
        }

        # Resolve diagnostics fields from preprocessing or response fallbacks.
        request_id: str | None = None
        processor_version: str | None = None
        max_frames_actual: int | None = None
        sampled_frames: list[dict[str, Any]] | None = None
        deployment_manifest: dict[str, Any] | None = None
        if preprocessing is not None:
            request_id = preprocessing.get("request_id")
            processor_version = preprocessing.get("processor_version")
            max_frames = preprocessing.get("max_frames")
            if isinstance(max_frames, int) and max_frames > 0:
                max_frames_actual = max_frames
            sampled_frames = preprocessing.get("frames")
            deployment_manifest = preprocessing.get("deployment_manifest")
        if request_id is None:
            request_id = response_id

        error_info: ValidationErrorInfo | None = None
        if parse_result.error is not None:
            error_info = ValidationErrorInfo(
                code=parse_result.error.code,
                message=parse_result.error.message,
                field=parse_result.error.field,
            )

        diagnostics = SampleAndInferDiagnostics(
            request_id=request_id,
            processor_version=processor_version,
            max_frames=max_frames_actual,
            sampled_frames=sampled_frames,
            deployment_manifest=deployment_manifest,
            mime_type=DEFAULT_MIME_TYPE,
            base64_length=len(base64_payload),
            raw_http_response=raw_http_response,
            transport_retries=transport_retries,
            correction_retries=max(0, parse_result.attempts - 1),
            elapsed_seconds=round(infer_elapsed, 6),
            error=error_info,
        )

        return InferenceResult(
            ok=parse_result.ok,
            model_output=parse_result.data,
            error=parse_result.error,
            attempts=parse_result.attempts,
            preprocessing=preprocessing,
            diagnostics=diagnostics,
        )


class MockInferenceClient:
    """Test-friendly inference client that returns a canned response.

    The ``response`` callable receives ``(video_input, prompt)`` and should
    return either a raw text string or a dict.  Dicts are returned as-is;
    strings are parsed by ``ResultParser``.  For strings, an unsuccessful
    ``InferenceResult`` is returned when the text cannot be parsed or does not
    satisfy the model-output schema.
    """

    def __init__(self, response: dict | str | Callable[..., Any]) -> None:
        self._response = response

    def infer(
        self, video_input: str | ClipBuildResult, prompt: str
    ) -> InferenceResult:
        if callable(self._response):
            raw = self._response(video_input, prompt)
        else:
            raw = self._response

        if isinstance(raw, dict):
            return InferenceResult(ok=True, model_output=raw, attempts=1)

        parsed = ResultParser.parse(raw)
        if parsed.ok:
            return InferenceResult(ok=True, model_output=parsed.data, attempts=1)
        return InferenceResult(ok=False, error=parsed.error, attempts=1)


def create_inference_client(config: dict[str, Any] | None = None) -> InferenceClient:
    """Factory for an ``InferenceClient`` from configuration.

    If ``INFERENCE_MOCK=1`` is set in the environment, a ``MockInferenceClient``
    returning a harmless negative result is created so that unit tests and
    offline development do not require a running inference server.
    """
    if os.getenv("INFERENCE_MOCK") == "1":
        return MockInferenceClient({
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
            "confidence": 0.5,
        })

    cfg = config or {}
    backend_cfg = cfg.get("backend", {})

    # Priority: config file > environment variable > default
    base_url = (
        backend_cfg.get("api_url")
        or os.getenv("INFERENCE_BASE_URL")
        or "http://localhost:8000/v1"
    )
    model = backend_cfg.get("model") or os.getenv("INFERENCE_MODEL") or "minicpmv4_5"
    api_key = os.getenv("INFERENCE_API_KEY") or "EMPTY"

    return LlamaFactoryInferenceClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
