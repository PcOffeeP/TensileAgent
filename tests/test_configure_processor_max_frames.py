from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing.minicpm_preprocessor import configure_processor_max_frames


def test_4_5_style_processor_sets_image_processor_max_frames():
    """4.5 风格 processor：只有 image_processor.max_frames，应修改并返回顶层 processor。"""
    image_processor = SimpleNamespace(max_frames=32)
    proc = SimpleNamespace(image_processor=image_processor)

    returned = configure_processor_max_frames(proc, 8)

    assert returned is proc
    assert proc.image_processor.max_frames == 8


def test_4_6_style_processor_returns_video_processor():
    """4.6 风格 processor：video_processor 拥有 max_frames，应修改并返回该子组件。"""
    video_processor = SimpleNamespace(max_frames=32)
    proc = SimpleNamespace(video_processor=video_processor)

    returned = configure_processor_max_frames(proc, 8)

    assert returned is proc.video_processor
    assert proc.video_processor.max_frames == 8


def test_falls_back_to_config_video_maxlen():
    """无 image/video processor 时，应回退到 config.video_maxlen 并返回顶层 processor。"""
    config = SimpleNamespace(video_maxlen=16)
    proc = SimpleNamespace(config=config)

    returned = configure_processor_max_frames(proc, 8)

    assert returned is proc
    assert proc.config.video_maxlen == 8


def test_raises_when_no_settable_attribute_found():
    """没有任何可设置 max-frame 参数时，应抛出 RuntimeError。"""
    proc = SimpleNamespace()

    with pytest.raises(RuntimeError, match="cannot locate MiniCPM actual max-frame parameter"):
        configure_processor_max_frames(proc, 8)


def test_raises_when_max_frames_not_8():
    """max_frames 不为 8 时，应抛出 ValueError。"""
    proc = SimpleNamespace(max_frames=32)

    with pytest.raises(ValueError, match="MiniCPM-V contract requires max_frames=8"):
        configure_processor_max_frames(proc, 4)
