from __future__ import annotations

import base64

import pytest

from pipeline.llamafactory_contract import CapturingVideoProcessor, configure_loaded_processor
from pipeline.server_proxy import _decode_mp4_data_url, _extract_video_data_url


def _payload(data: bytes = b"mp4") -> dict:
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{encoded}"}},
                {"type": "text", "text": "inspect"},
            ],
        }]
    }


def test_request_media_extraction_is_strict_base64_mp4():
    data_url = _extract_video_data_url(_payload(b"exact-media"))
    assert _decode_mp4_data_url(data_url) == b"exact-media"


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": []},
        {"messages": [{"content": [{"type": "video_url", "video_url": {"url": "file:///tmp/a.mp4"}}]}]},
    ],
)
def test_request_rejects_missing_or_non_base64_video(payload):
    if payload["messages"]:
        data_url = _extract_video_data_url(payload)
        with pytest.raises(ValueError):
            _decode_mp4_data_url(data_url)
    else:
        with pytest.raises(ValueError):
            _extract_video_data_url(payload)


def test_loaded_inference_processor_is_configured_and_wrapped():
    class VideoProcessor:
        max_frames = 32

    class Processor:
        def __init__(self):
            self.video_processor = VideoProcessor()

    processor = Processor()
    capture = configure_loaded_processor(processor, capture=True)

    assert isinstance(capture, CapturingVideoProcessor)
    assert processor.video_processor is capture
    assert capture.max_frames == 8
