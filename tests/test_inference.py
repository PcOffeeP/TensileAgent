from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent.inference import (
    DEFAULT_MAX_REQUEST_SIZE,
    InferenceResult,
    LlamaFactoryInferenceClient,
    MockInferenceClient,
    _encode_video_to_data_url,
    _is_mp4_file,
    _redact_data_url,
    create_inference_client,
)
from agent.sampling import ClipBuildResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_FAKE_MP4_HEADER = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp41"


def _write_fake_mp4(path: Path, content: bytes = b"video-bytes") -> None:
    """Write a minimal ISO-BMFF ``ftyp`` box so MIME validation passes."""
    path.write_bytes(_FAKE_MP4_HEADER + content)


# ---------------------------------------------------------------------------
# MockInferenceClient
# ---------------------------------------------------------------------------
def test_mock_inference_client_returns_dict():
    client = MockInferenceClient({
        "has_fracture": True,
        "fracture_between": [17, 18],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    })
    result = client.infer("any.mp4", "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is True
    assert result.model_output["type"] == "韧性断裂"


def test_mock_inference_client_parses_json_string():
    client = MockInferenceClient(
        '{"has_fracture": false, "fracture_between": null, "type": "未断裂", '
        '"location": null, "confidence": 0.6}'
    )
    result = client.infer("any.mp4", "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is False
    assert result.model_output["location"] is None
    assert result.model_output["confidence"] == pytest.approx(0.6)


def test_mock_inference_client_callable_response():
    def responder(video_input: str, prompt: str) -> dict:
        assert isinstance(video_input, str)
        return {
            "has_fracture": True,
            "fracture_between": [0, 1],
            "type": "脆性断裂",
            "location": "outside_gauge",
            "confidence": 0.8,
        }

    client = MockInferenceClient(responder)
    result = client.infer("clip.mp4", "analyze")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "脆性断裂"


def test_mock_inference_client_accepts_clip_build_result():
    clip = ClipBuildResult(path="/tmp/clip.mp4", manifest=[{"temp_index": 0}])

    def responder(video_input, prompt: str) -> dict:
        assert isinstance(video_input, ClipBuildResult)
        return {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
            "confidence": 0.7,
        }

    client = MockInferenceClient(responder)
    result = client.infer(clip, "prompt")
    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"


def test_mock_inference_client_invalid_response_returns_failure():
    client = MockInferenceClient("not valid json")
    result = client.infer("any.mp4", "prompt")
    assert not result.ok
    assert result.model_output is None
    assert result.error is not None
    assert result.attempts == 1


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def test_create_inference_client_mock_mode():
    with patch.dict("os.environ", {"INFERENCE_MOCK": "1"}):
        client = create_inference_client({})
        result = client.infer("any.mp4", "prompt")
        assert result.ok
        assert result.model_output is not None
        assert result.model_output["has_fracture"] is False
        assert result.model_output["type"] == "未断裂"
        assert result.model_output["location"] is None


# ---------------------------------------------------------------------------
# LlamaFactoryInferenceClient validation
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_missing_video():
    with patch("agent.inference.OpenAI"):
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FileNotFoundError):
            client.infer("/nonexistent.mp4", "prompt")


def test_llama_factory_inference_client_rejects_non_mp4_extension(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "fake.txt"
        video.write_text("content")
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(ValueError, match="Invalid or non-MP4"):
            client.infer(str(video), "prompt")


def test_llama_factory_inference_client_rejects_bad_mp4_signature(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "fake.mp4"
        video.write_text("not a real mp4")
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(ValueError, match="Invalid or non-MP4"):
            client.infer(str(video), "prompt")


def test_llama_factory_inference_client_accepts_valid_mp4_signature(tmp_path: Path):
    video = tmp_path / "valid.mp4"
    _write_fake_mp4(video)
    assert _is_mp4_file(str(video)) is True


def test_llama_factory_inference_client_payload_too_large(tmp_path: Path):
    with patch("agent.inference.OpenAI"):
        video = tmp_path / "big.mp4"
        _write_fake_mp4(video, b"x" * 200)
        client = LlamaFactoryInferenceClient(
            model="minicpm-test", max_request_size=10
        )
        with pytest.raises(RuntimeError, match="exceeds"):
            client.infer(str(video), "prompt")


# ---------------------------------------------------------------------------
# Base64 request format
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_sends_base64(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    raw_content = b"video content"
    _write_fake_mp4(video, raw_content)

    captured: dict[str, Any] = {}

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        captured["model"] = model
        captured["messages"] = messages
        captured["extra_body"] = extra_body
        mock_completion = MagicMock()
        mock_completion.model_dump.return_value = {}
        mock_completion.model_extra = {}
        mock_completion.preprocessing = None
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": true, "fracture_between": [2, 3], '
            '"type": "韧性断裂", "location": "inside_gauge", "confidence": 0.95}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze this")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["has_fracture"] is True
    assert result.model_output["confidence"] == pytest.approx(0.95)
    assert captured["model"] == "minicpm-test"

    # Message ordering: system first, then user with video_url before text.
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][1]["role"] == "user"
    user_content = captured["messages"][1]["content"]
    assert user_content[0]["type"] == "video_url"
    assert user_content[1]["type"] == "text"
    assert user_content[1]["text"] == "analyze this"

    url = user_content[0]["video_url"]["url"]
    assert url.startswith("data:video/mp4;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == _FAKE_MP4_HEADER + raw_content
    assert captured["extra_body"] is None


def test_llama_factory_inference_client_clip_build_result_sends_manifest(
    tmp_path: Path,
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    manifest = [{"temp_index": 0, "original_frame": 10, "timestamp": 1.0}]

    captured: dict[str, Any] = {}

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        captured["extra_body"] = extra_body
        mock_completion = MagicMock()
        mock_completion.model_dump.return_value = {}
        mock_completion.model_extra = {}
        mock_completion.preprocessing = None
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        clip = ClipBuildResult(path=str(video), manifest=manifest)
        result = client.infer(clip, "prompt")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert captured["extra_body"] == {"preprocessing": {"temp_video_manifest": manifest}}


# ---------------------------------------------------------------------------
# Transport retry
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_transport_retry(tmp_path: Path, monkeypatch):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    class FakeRetryableError(Exception):
        status_code = 503

    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {}
    mock_completion.model_extra = {}
    mock_completion.preprocessing = None
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = (
        '{"has_fracture": false, "fracture_between": null, '
        '"type": "未断裂", "location": null, "confidence": 0.8}'
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeRetryableError("server error"),
        mock_completion,
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "prompt")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert mock_client.chat.completions.create.call_count == 2


def test_llama_factory_inference_client_exhausts_retries(tmp_path: Path, monkeypatch):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    class FakeRetryableError(Exception):
        status_code = 502

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeRetryableError("err1"),
        FakeRetryableError("err2"),
        FakeRetryableError("err3"),
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FakeRetryableError, match="err3"):
            client.infer(str(video), "prompt")

    # Initial attempt + 2 retries = 3 calls.
    assert mock_client.chat.completions.create.call_count == 3


def test_llama_factory_inference_client_non_retryable_error(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    class FakeAuthError(Exception):
        status_code = 401

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = FakeAuthError("unauthorized")

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        with pytest.raises(FakeAuthError, match="unauthorized"):
            client.infer(str(video), "prompt")

    assert mock_client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# Model-output correction retries
# ---------------------------------------------------------------------------
def test_llama_factory_inference_client_correction_then_success(
    tmp_path: Path, monkeypatch
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    calls: list[list[dict[str, Any]]] = []

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        calls.append(messages)
        completion = MagicMock()
        completion.model_dump.return_value = {}
        completion.model_extra = {}
        completion.preprocessing = None
        completion.choices = [MagicMock()]
        if len(calls) == 1:
            completion.choices[0].message.content = "not valid json"
        else:
            completion.choices[0].message.content = (
                '{"has_fracture": false, "fracture_between": null, '
                '"type": "未断裂", "location": null, "confidence": 0.7}'
            )
        return completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert result.ok
    assert result.model_output is not None
    assert result.model_output["type"] == "未断裂"
    assert result.attempts == 2
    assert len(calls) == 2
    # The original system prompt and video-bearing user message are preserved.
    assert calls[1][0]["role"] == "system"
    assert calls[1][1]["role"] == "user"
    assert any(item.get("type") == "video_url" for item in calls[1][1]["content"])
    # The correction turn appends the parser error details.
    assert calls[1][-1]["role"] == "user"
    assert "invalid_json" in calls[1][-1]["content"]


def test_llama_factory_inference_client_correction_exhausted(
    tmp_path: Path, monkeypatch
):
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    def make_completion(content: str):
        completion = MagicMock()
        completion.model_dump.return_value = {}
        completion.model_extra = {}
        completion.preprocessing = None
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = content
        return completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        make_completion("not valid json"),
        make_completion("{\"has_fracture\": true}"),
        make_completion("{\"unexpected\": 1}"),
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert not result.ok
    assert result.model_output is None
    assert result.error is not None
    assert result.error.code == "invalid_model_output"
    assert result.attempts == 3
    assert mock_client.chat.completions.create.call_count == 3


# ---------------------------------------------------------------------------
# Sensitive information redaction
# ---------------------------------------------------------------------------
def test_redact_data_url():
    url = "data:video/mp4;base64," + "A" * 200
    redacted = _redact_data_url(url)
    assert redacted.startswith("data:video/mp4;base64,[REDACTED:")
    assert "[REDACTED:" in redacted
    assert "A" * 190 not in redacted


@pytest.mark.parametrize("payload_len", [1, 8, 32, 33, 64, 65])
def test_redact_data_url_redacts_any_non_empty_payload(payload_len: int):
    """Any non-empty Base64 payload must be length-tokenized, never returned verbatim."""
    # Use a character that does not appear in the prefix/marker to avoid false positives.
    payload = "X" * payload_len
    url = "data:video/mp4;base64," + payload
    redacted = _redact_data_url(url)
    assert redacted.startswith("data:video/mp4;base64,")
    assert "[REDACTED:" in redacted
    assert payload not in redacted


def test_logs_do_not_contain_full_base64(tmp_path: Path, caplog):
    video = tmp_path / "clip.mp4"
    secret = b"secret video bytes " * 10
    _write_fake_mp4(video, secret)
    data_url = _encode_video_to_data_url(str(video))

    with caplog.at_level(logging.INFO, logger="agent.inference"):
        logger = logging.getLogger("agent.inference")
        logger.info("payload preview: %s", _redact_data_url(data_url))

    assert data_url not in caplog.text
    assert base64.b64encode(secret).decode("ascii") not in caplog.text
    assert "[REDACTED:" in caplog.text


def test_client_repr_does_not_leak_api_key():
    with patch("agent.inference.OpenAI"):
        client = LlamaFactoryInferenceClient(
            model="m", api_key="super-secret-key"
        )
        representation = repr(client)
        assert "super-secret-key" not in representation
        assert "***REDACTED***" in representation


# ---------------------------------------------------------------------------
# Default constants sanity checks
# ---------------------------------------------------------------------------
def test_default_request_size_is_32_mib():
    assert DEFAULT_MAX_REQUEST_SIZE == 32 * 1024 * 1024


# ---------------------------------------------------------------------------
# Preprocessing metadata extraction and validation
# ---------------------------------------------------------------------------
def test_validate_preprocessing_meta_none():
    from agent.inference import _validate_preprocessing_meta
    assert _validate_preprocessing_meta(None) == "missing_or_invalid_preprocessing_metadata"


def test_validate_preprocessing_meta_max_frames_not_8():
    """max_frames != 8 is fatal."""
    from agent.inference import _validate_preprocessing_meta
    meta = {"request_id": "r", "processor_version": "v", "max_frames": 4, "frames": []}
    assert _validate_preprocessing_meta(meta) == "max_frames_not_8"


def test_validate_preprocessing_meta_too_many_frames():
    from agent.inference import _validate_preprocessing_meta
    meta = {"request_id": "r", "processor_version": "v", "max_frames": 8, "frames": [{"index": i, "timestamp": float(i)} for i in range(9)]}
    assert _validate_preprocessing_meta(meta) == "too_many_frames"


def test_validate_preprocessing_meta_non_monotonic_indices():
    from agent.inference import _validate_preprocessing_meta
    meta = {
        "max_frames": 8,
        "request_id": "r", "processor_version": "v",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "frames": [
            {"index": 0, "timestamp": 0.0},
            {"index": 2, "timestamp": 1.0},
            {"index": 1, "timestamp": 2.0},  # not monotonic
        ],
    }
    assert _validate_preprocessing_meta(meta) == "non_monotonic_indices"


def test_validate_preprocessing_meta_duplicate_index():
    from agent.inference import _validate_preprocessing_meta
    meta = {
        "max_frames": 8,
        "request_id": "r", "processor_version": "v",
        "frames": [
            {"index": 0, "timestamp": 0.0},
            {"index": 1, "timestamp": 1.0},
            {"index": 1, "timestamp": 2.0},  # not strictly increasing
        ],
    }
    assert _validate_preprocessing_meta(meta) == "non_monotonic_indices"


def test_validate_preprocessing_meta_valid():
    from agent.inference import _validate_preprocessing_meta
    meta = {
        "max_frames": 8,
        "request_id": "r", "processor_version": "v",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "frames": [
            {"index": 0, "timestamp": 0.0},
            {"index": 1, "timestamp": 1.5},
            {"index": 2, "timestamp": 3.0},
        ],
    }
    assert _validate_preprocessing_meta(meta) is None


def test_validate_preprocessing_meta_non_continuous_indices():
    """Indices with gaps (non-continuous) are fatal."""
    from agent.inference import _validate_preprocessing_meta
    meta = {
        "max_frames": 8,
        "request_id": "r", "processor_version": "v",
        "frames": [
            {"index": 0, "timestamp": 0.0},
            {"index": 2, "timestamp": 1.0},
            {"index": 5, "timestamp": 2.0},
        ],
    }
    assert _validate_preprocessing_meta(meta) == "non_monotonic_indices"


def test_extract_preprocessing_from_response_model_dump():
    """Extract via model_dump() when extra fields are included."""
    from agent.inference import _extract_preprocessing_from_response

    class FakeResponse:
        def model_dump(self):
            return {
                "id": "chatcmpl-xxx",
                "preprocessing": {
                    "request_id": "uuid-1",
                    "processor_version": "minicpmv4.5/0.1",
                    "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
                    "max_frames": 8,
                    "frames": [{"index": 0, "timestamp": 1.0}],
                },
            }

    result = _extract_preprocessing_from_response(FakeResponse())
    assert result is not None
    assert result["request_id"] == "uuid-1"
    assert result["max_frames"] == 8


def test_extract_preprocessing_from_response_model_extra():
    """Extract via model_extra dict (Pydantic v2)."""
    from agent.inference import _extract_preprocessing_from_response

    class FakeResponse:
        model_extra = {
            "preprocessing": {
                "request_id": "uuid-2",
                "processor_version": "minicpmv4.5/0.1",
                "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
                "max_frames": 8,
                "frames": [{"index": 0, "timestamp": 1.0}],
            },
        }

        def model_dump(self):
            return {"id": "chatcmpl-xxx"}

    result = _extract_preprocessing_from_response(FakeResponse())
    assert result is not None
    assert result["request_id"] == "uuid-2"


def test_extract_preprocessing_from_response_direct_attr():
    """Extract via direct attribute access (test mocks)."""
    from agent.inference import _extract_preprocessing_from_response

    class FakeResponse:
        preprocessing = {
            "request_id": "uuid-3",
            "processor_version": "minicpmv4.5/0.1",
            "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
            "max_frames": 8,
            "frames": [{"index": 0, "timestamp": 1.0}],
        }

        def model_dump(self):
            return {"id": "chatcmpl-xxx"}

    result = _extract_preprocessing_from_response(FakeResponse())
    assert result is not None
    assert result["request_id"] == "uuid-3"


def test_extract_preprocessing_from_response_absent():
    from agent.inference import _extract_preprocessing_from_response

    class FakeResponse:
        def model_dump(self):
            return {"id": "chatcmpl-xxx"}

    result = _extract_preprocessing_from_response(FakeResponse())
    assert result is None


def test_llama_factory_inference_client_extracts_preprocessing(tmp_path: Path):
    """End-to-end: LlamaFactoryInferenceClient extracts preprocessing from response."""
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    preprocessing_payload = {
        "request_id": "e2e-uuid",
        "processor_version": "minicpmv4.5/0.1",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "max_frames": 8,
        "frames": [
            {"index": 0, "timestamp": 0.0},
            {"index": 4, "timestamp": 2.0},
            {"index": 7, "timestamp": 3.5},
        ],
    }

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        # Inject preprocessing via model_extra
        mock_completion.model_extra = {"preprocessing": preprocessing_payload}

        def model_dump():
            return {"id": "chatcmpl-e2e", "choices": [{"index": 0}]}
        mock_completion.model_dump = model_dump
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert result.ok
    assert result.preprocessing is not None
    assert result.preprocessing["request_id"] == "e2e-uuid"
    assert result.preprocessing["max_frames"] == 8
    assert len(result.preprocessing["frames"]) == 3


def test_llama_factory_inference_client_extracts_invalid_preprocessing(
    tmp_path: Path,
):
    """Invalid preprocessing is still stored (caller validates)."""
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    preprocessing_payload = {
        "request_id": "invalid-uuid",
        "processor_version": "old",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "max_frames": 4,  # Not 8
        "frames": [{"index": 0, "timestamp": 0.0}],
    }

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        mock_completion.model_extra = {"preprocessing": preprocessing_payload}

        def model_dump():
            return {"id": "chatcmpl-invalid"}
        mock_completion.model_dump = model_dump
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    # Invalid preprocessing is still stored (raw) for caller to validate.
    assert result.preprocessing is not None
    assert result.preprocessing["max_frames"] == 4  # raw value preserved


def test_llama_factory_inference_client_no_preprocessing_is_graceful(
    tmp_path: Path,
):
    """Missing preprocessing does not crash — preprocessing field is None."""
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    class _ResponseStub:
        """Stub that mimics ChatCompletion without preprocessing."""
        class _Choice:
            class _Message:
                content = (
                    '{"has_fracture": false, "fracture_between": null, '
                    '"type": "未断裂", "location": null, "confidence": 0.8}'
                )
            message = _Message()

        choices = [_Choice()]
        model_extra: dict = {}

        @staticmethod
        def model_dump():
            return {"id": "chatcmpl-nope"}

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        return _ResponseStub()

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert result.ok
    assert result.preprocessing is None  # graceful degradation


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
def test_inference_result_includes_diagnostics(tmp_path: Path):
    """A successful inference call must populate diagnostics fields."""
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        mock_completion = MagicMock()
        mock_completion.model_dump.return_value = {
            "id": "chatcmpl-diag",
            "model": model,
        }
        mock_completion.model_extra = {}
        mock_completion.preprocessing = {
            "request_id": "req-123",
            "processor_version": "minicpmv4.5/0.1",
            "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
            "max_frames": 8,
            "frames": [{"index": 0, "timestamp": 0.0}],
        }
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "analyze")

    assert result.ok
    assert result.diagnostics is not None
    assert result.diagnostics.request_id == "req-123"
    assert result.diagnostics.processor_version == "minicpmv4.5/0.1"
    assert result.diagnostics.max_frames == 8
    assert result.diagnostics.sampled_frames is not None
    assert result.diagnostics.mime_type == "video/mp4"
    assert result.diagnostics.base64_length > 0
    assert result.diagnostics.raw_http_response is not None
    assert result.diagnostics.transport_retries == 0
    assert result.diagnostics.correction_retries == 0
    assert result.diagnostics.elapsed_seconds is not None


def test_diagnostics_transport_retries(tmp_path: Path, monkeypatch):
    """Transport retries must be counted in diagnostics."""
    video = tmp_path / "clip.mp4"
    _write_fake_mp4(video)
    monkeypatch.setattr("agent.inference.time.sleep", lambda _s: None)

    class FakeRetryableError(Exception):
        status_code = 503

    mock_completion = MagicMock()
    mock_completion.model_dump.return_value = {"id": "chatcmpl-retry"}
    mock_completion.model_extra = {}
    mock_completion.preprocessing = None
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = (
        '{"has_fracture": false, "fracture_between": null, '
        '"type": "未断裂", "location": null, "confidence": 0.8}'
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        FakeRetryableError("server error"),
        mock_completion,
    ]

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "prompt")

    assert result.ok
    assert result.diagnostics is not None
    assert result.diagnostics.transport_retries == 1


def test_diagnostics_do_not_leak_base64(tmp_path: Path):
    """Diagnostics raw_http_response must not contain the full Base64 payload."""
    video = tmp_path / "clip.mp4"
    secret = b"secret video bytes " * 50
    _write_fake_mp4(video, secret)

    captured_messages: list[list[dict[str, Any]]] = []

    def fake_create(*, model, messages, temperature, max_tokens, extra_body=None):
        captured_messages.append(messages)
        mock_completion = MagicMock()
        mock_completion.model_dump.return_value = {"id": "chatcmpl-redact"}
        mock_completion.model_extra = {}
        mock_completion.preprocessing = None
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = (
            '{"has_fracture": false, "fracture_between": null, '
            '"type": "未断裂", "location": null, "confidence": 0.8}'
        )
        return mock_completion

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = fake_create

    with patch("agent.inference.OpenAI") as mock_openai:
        mock_openai.return_value = mock_client
        client = LlamaFactoryInferenceClient(model="minicpm-test")
        result = client.infer(str(video), "prompt")

    assert result.ok
    diagnostics = result.diagnostics
    assert diagnostics is not None
    raw = diagnostics.raw_http_response
    assert raw is not None
    request_messages = raw["request"]["messages"]
    user_content = request_messages[1]["content"]
    video_url = user_content[0]["video_url"]["url"]
    assert "[REDACTED:" in video_url
    # The original full base64 payload must not appear anywhere in diagnostics.
    diagnostics_json = json.dumps(diagnostics.model_dump(mode="json"))
    import base64
    full_payload = base64.b64encode(_FAKE_MP4_HEADER + secret).decode("ascii")
    assert full_payload not in diagnostics_json
TEST_DEPLOYMENT_MANIFEST = {
    "model_version": "minicpm-v-4.5",
    "transformers_version": "4.test",
    "llamafactory_version": "test-rev",
    "base_model_version": "base-test",
    "artifact_version": "adapter-test",
    "config_fingerprint": "sha256:test",
    "runtime_device": "cpu",
    "runtime_dtype": "float32",
}
