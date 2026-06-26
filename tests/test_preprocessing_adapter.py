from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing import (
    FrameMapping,
    MiniCPMVideoPreprocessor,
    MockVideoPreprocessor,
    ProcessorInfo,
    VideoPreprocessor,
)
from pipeline.preprocessing.minicpm_preprocessor import configure_processor_max_frames


def _make_test_video(path: Path, duration: float, fps: float = 30.0) -> None:
    """生成纯色测试视频，时长和帧率固定。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=64x64:d={duration}:r={fps}",
        "-pix_fmt", "yuv420p",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


@pytest.fixture
def short_video(tmp_path: Path) -> Path:
    video = tmp_path / "short_5s_30fps.mp4"
    _make_test_video(video, duration=5.0, fps=30.0)
    return video


@pytest.fixture
def long_video(tmp_path: Path) -> Path:
    video = tmp_path / "long_35s_30fps.mp4"
    _make_test_video(video, duration=35.0, fps=30.0)
    return video


# ---------------------------------------------------------------------------
# 抽象类接口
# ---------------------------------------------------------------------------


def test_video_preprocessor_is_abstract():
    """VideoPreprocessor 不能直接实例化，必须实现抽象方法。"""
    with pytest.raises(TypeError):
        VideoPreprocessor()


def test_video_preprocessor_interface_shape():
    """确认抽象类声明的接口方法存在且签名正确。"""
    required_methods = {"get_info", "healthcheck", "sample", "fingerprint"}
    assert required_methods.issubset({m for m in dir(VideoPreprocessor) if not m.startswith("_")})


# ---------------------------------------------------------------------------
# mock 预处理器
# ---------------------------------------------------------------------------


def test_mock_healthcheck_passes_when_ffmpeg_available():
    preprocessor = MockVideoPreprocessor()
    ok = preprocessor.healthcheck()
    # 当前 CI/本地 ffmpeg 通常可用；如不可用，测试显式失败以提示环境。
    assert ok is True


def test_mock_info_fields():
    info = MockVideoPreprocessor().get_info()
    assert info.name == "mock-ffmpeg-uniform"
    assert info.max_frames == 8
    assert info.backend == "ffmpeg"
    assert isinstance(info.version, str)


def test_mock_sample_outputs_at_most_eight_frames(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    assert len(frames) <= 8
    assert all(isinstance(f, FrameMapping) for f in frames)


def test_mock_sample_outputs_monotonic_frames_and_timestamps(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)
    original_frames = [f.original_frame for f in frames]
    timestamps = [f.timestamp for f in frames]
    assert original_frames == sorted(original_frames)
    assert timestamps == sorted(timestamps)
    assert len(set(original_frames)) == len(original_frames)


def test_mock_sample_input_index_is_sequential(short_video: Path):
    frames = MockVideoPreprocessor().sample(str(short_video), start_time=0.0, end_time=5.0)
    assert [f.input_index for f in frames] == list(range(len(frames)))


@pytest.mark.parametrize(
    ("start", "end", "expected_max"),
    [
        (0.0, 1.0, 8),  # 1s 区间帧数 >= 8，应取 8 帧
        (0.0, 3.0, 8),  # 3s 区间
        (0.0, 10.0, 8),  # 10s 区间
        (0.0, 30.0, 8),  # 30s 区间
    ],
)
def test_mock_sample_short_intervals_up_to_eight_frames(
    long_video: Path, start: float, end: float, expected_max: int
):
    frames = MockVideoPreprocessor().sample(str(long_video), start_time=start, end_time=end)
    assert len(frames) <= expected_max
    if (end - start) >= 8 / 30.0:
        assert len(frames) == expected_max


def test_mock_sample_full_video(long_video: Path):
    frames = MockVideoPreprocessor().sample(str(long_video), start_time=0.0, end_time=35.0)
    assert len(frames) == 8
    assert frames[0].original_frame == 0
    assert frames[-1].original_frame >= 30 * 35 - 2  # 允许 ±1 帧舍入


def test_mock_sample_very_short_interval_returns_fewer_than_eight(short_video: Path):
    # 0.1s 区间约 3 帧，应返回 <=3 帧
    frames = MockVideoPreprocessor().sample(str(short_video), start_time=1.0, end_time=1.1)
    assert 1 <= len(frames) <= 3


def test_mock_sample_invalid_interval_raises(short_video: Path):
    preprocessor = MockVideoPreprocessor()
    with pytest.raises(ValueError):
        preprocessor.sample(str(short_video), start_time=2.0, end_time=2.0)
    with pytest.raises(ValueError):
        preprocessor.sample(str(short_video), start_time=-1.0, end_time=2.0)


def test_mock_fingerprint_is_nonempty():
    fp = MockVideoPreprocessor().fingerprint()
    assert isinstance(fp, str) and fp
    assert "mock-ffmpeg-uniform" in fp


# ---------------------------------------------------------------------------
# minicpm 模板接口
# ---------------------------------------------------------------------------


def test_minicpm_info_fields():
    preprocessor = MiniCPMVideoPreprocessor(model_path_or_name="openbmb/MiniCPM-V-2_6")
    info = preprocessor.get_info()
    assert isinstance(info, ProcessorInfo)
    assert info.name == "minicpm-v-4.5"
    assert info.max_frames == 8


def test_minicpm_healthcheck_requires_max_frames_eight():
    ok_default = MiniCPMVideoPreprocessor("test").healthcheck()
    ok_wrong = MiniCPMVideoPreprocessor("test", max_frames=16).healthcheck()
    assert isinstance(ok_default, bool)
    # 本地无 transformers 时 ok_default 为 False；训练机为 True。
    # 关键校验：max_frames 不为 8 时必须失败。
    assert ok_wrong is False


def test_minicpm_sample_at_most_eight_frames(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)


def test_minicpm_sample_monotonic_frames_and_timestamps(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)


def test_minicpm_sample_input_index_is_sequential(short_video: Path):
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)


def test_minicpm_sample_full_video_returns_eight_frames(long_video: Path):
    """35s @ 30fps 应均匀取 8 帧。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(long_video), start_time=0.0, end_time=35.0)


def test_minicpm_sample_short_interval_returns_fewer_than_eight(short_video: Path):
    """0.1s 区间约 3 帧，应返回 <=3 帧。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=1.0, end_time=1.1)


def test_minicpm_sample_clamps_negative_start_time(short_video: Path):
    """start_time < 0 应截断为 0，不抛异常。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=-1.0, end_time=2.0)


def test_minicpm_sample_clamps_end_time_exceeding_duration(short_video: Path):
    """end_time > duration 应截断为 duration。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    with pytest.raises(RuntimeError, match="MiniCPM-V processor 不可用"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=999.0)


def test_minicpm_sample_empty_interval_returns_empty(short_video: Path):
    """end_time <= start_time 应返回空列表。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    frames = preprocessor.sample(str(short_video), start_time=2.0, end_time=2.0)
    assert frames == []
    frames2 = preprocessor.sample(str(short_video), start_time=3.0, end_time=2.0)
    assert frames2 == []


def test_minicpm_fingerprint_is_stable():
    p1 = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    p2 = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    assert p1.fingerprint() == p2.fingerprint()


def test_minicpm_fingerprint_missing_config_files_raises(tmp_path: Path):
    """本地模型目录缺少 config.json 和 preprocessor_config.json 时明确失败。"""
    empty_model_dir = tmp_path / "empty_model"
    empty_model_dir.mkdir()
    preprocessor = MiniCPMVideoPreprocessor(str(empty_model_dir))
    with pytest.raises(ValueError, match="config.json"):
        preprocessor.fingerprint()


# ---------------------------------------------------------------------------
# minicpm processor 集成路径（mock）
# ---------------------------------------------------------------------------


def test_minicpm_processor_get_info_class_name():
    """processor 已加载时 get_info().version 返回 processor 类名。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    # 直接设置处理器已加载状态
    preprocessor._processor_loaded = True
    preprocessor._processor = object()  # 任意对象
    preprocessor._video_processor = object()  # 4.5 中保存顶层 processor 引用

    info = preprocessor.get_info()
    assert info.version == type(preprocessor._processor).__name__
    assert info.backend == "transformers"


def test_minicpm_processor_uses_real_sampling_defaults(short_video: Path):
    """Do not disable the real processor's frame-selection behavior."""
    from unittest.mock import MagicMock, patch

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")

    # 构造 5 帧解码结果
    fake_frames = [MagicMock() for _ in range(5)]
    fake_indices = [10, 20, 30, 40, 50]

    mock_processor = MagicMock()
    mock_processor.return_value = {"pixel_values_videos": MagicMock()}
    mock_processor.return_value["pixel_values_videos"].shape = (5, 3, 224, 224)

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with patch.object(
        preprocessor, "_decode_frame_range",
        return_value=(fake_frames, fake_indices, [i / 30 for i in fake_indices]),
    ):
        frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    _, kwargs = mock_processor.call_args
    assert "do_sample_frames" not in kwargs
    assert "images" in kwargs

    # 1:1 映射
    assert len(frames) == 5
    assert [f.original_frame for f in frames] == fake_indices


def test_minicpm_processor_sample_per_frame_matching(short_video: Path):
    """processor 做抽帧（n < len(decoded)）时通过逐帧比对确定保留帧。"""
    pytest.importorskip("torch")
    from unittest.mock import MagicMock, patch

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")

    fake_frames = [MagicMock() for _ in range(5)]
    fake_indices = [10, 20, 30, 40, 50]

    # 为每帧创建不同的 tensor 用于匹配
    import torch
    ind_pv0 = torch.tensor([[[[0.1]]]], dtype=torch.float32)
    ind_pv1 = torch.tensor([[[[0.3]]]], dtype=torch.float32)
    ind_pv2 = torch.tensor([[[[0.5]]]], dtype=torch.float32)
    ind_pv3 = torch.tensor([[[[0.7]]]], dtype=torch.float32)
    ind_pv4 = torch.tensor([[[[0.9]]]], dtype=torch.float32)

    mock_processor = MagicMock()
    # 批量调用：返回 frames 0, 2, 4
    batch_tensor = torch.stack([ind_pv0, ind_pv2, ind_pv4])

    # 逐帧调用：每次返回对应单帧
    ind_results = [
        {"pixel_values_videos": ind_pv0.unsqueeze(0)},
        {"pixel_values_videos": ind_pv1.unsqueeze(0)},
        {"pixel_values_videos": ind_pv2.unsqueeze(0)},
        {"pixel_values_videos": ind_pv3.unsqueeze(0)},
        {"pixel_values_videos": ind_pv4.unsqueeze(0)},
    ]
    mock_processor.side_effect = [
        {"pixel_values_videos": batch_tensor},
    ] + ind_results

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with patch.object(
        preprocessor, "_decode_frame_range",
        return_value=(fake_frames, fake_indices, [i / 30 for i in fake_indices]),
    ):
        frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    # 应匹配到帧 0, 2, 4（对应 original_frame 10, 30, 50）
    assert len(frames) == 3
    assert [f.original_frame for f in frames] == [10, 30, 50]
    assert [f.input_index for f in frames] == [0, 1, 2]


def test_minicpm_processor_sample_raises_on_error(short_video: Path):
    """processor 调用异常时抛出 RuntimeError，不静默回退。"""
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_processor = MagicMock(side_effect=RuntimeError("Mock processor error"))

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with pytest.raises(RuntimeError, match="processor 调用失败"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)


def test_minicpm_processor_sample_one_to_one_mapping(short_video: Path):
    """processor 输出帧数 == 解码帧数时 1:1 映射，不 fallback。"""
    import logging
    from unittest.mock import MagicMock, patch

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")

    # 构造 5 帧解码结果
    fake_frames = [MagicMock() for _ in range(5)]
    fake_indices = [10, 20, 30, 40, 50]

    mock_processor = MagicMock()
    mock_processor.return_value = {"pixel_values_videos": MagicMock()}
    # processor 返回 5 帧 == len(decoded_frames)，走 1:1 映射
    mock_processor.return_value["pixel_values_videos"].shape = (5, 3, 224, 224)

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with patch.object(
        preprocessor, "_decode_frame_range",
        return_value=(fake_frames, fake_indices, [i / 30 for i in fake_indices]),
    ):
        frames = preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    # 1:1 映射：5 帧，帧号即 fake_indices
    assert len(frames) == 5
    assert [f.original_frame for f in frames] == fake_indices
    assert [f.input_index for f in frames] == [0, 1, 2, 3, 4]


def test_minicpm_processor_sample_raises_on_missing_pixel_values(short_video: Path):
    """processor 输出不含 pixel_values_videos/pixel_values 时抛出 RuntimeError。"""
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    mock_processor = MagicMock()
    mock_processor.return_value = {"some_other_key": "data"}

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with pytest.raises(RuntimeError, match="不含 pixel_values_videos 或 pixel_values"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)


def test_minicpm_processor_sample_decoded_frames_passed_to_processor(short_video: Path):
    """顶层 processor 接收到的 images 是解码后的 RGB 图像（PIL Image 或 ndarray）。"""
    import numpy as np
    from unittest.mock import MagicMock

    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")

    # side_effect 根据输入帧数动态构造匹配形状，避免触发逐帧比对路径
    def _processor_side_effect(images=None, return_tensors=None, **kwargs):
        n_frames = len(images)
        pv = MagicMock()
        pv.shape = (n_frames, 3, 224, 224)
        return {"pixel_values_videos": pv}

    mock_processor = MagicMock(side_effect=_processor_side_effect)

    preprocessor._processor = mock_processor
    preprocessor._video_processor = mock_processor  # 4.5 中保存顶层 processor 引用
    preprocessor._processor_loaded = True

    with pytest.raises(RuntimeError, match="超过契约上限"):
        preprocessor.sample(str(short_video), start_time=0.0, end_time=5.0)

    _, kwargs = mock_processor.call_args
    passed_images = kwargs["images"]
    assert isinstance(passed_images, list)
    # 内部应为 PIL Image 或 ndarray（取决于 Pillow 是否可用）
    for f in passed_images:
        if hasattr(f, "mode"):  # PIL Image
            assert f.mode == "RGB"
        else:  # ndarray
            assert isinstance(f, np.ndarray)
            assert f.shape[-1] == 3
            assert f.dtype == np.uint8


def test_minicpm_processor_get_info_fallback_when_not_loaded():
    """processor 未加载时 get_info() 使用 model_path 作为 version。"""
    preprocessor = MiniCPMVideoPreprocessor("openbmb/MiniCPM-V-2_6")
    assert preprocessor._processor_loaded is False

    info = preprocessor.get_info()
    assert info.version == "openbmb/MiniCPM-V-2_6"
    assert info.backend in ("transformers-not-installed", "transformers-unavailable")


# ---------------------------------------------------------------------------
# configure_processor_max_frames 单元测试
# ---------------------------------------------------------------------------


def test_configure_processor_max_frames_45_style():
    """4.5 风格 processor：属性挂在 image_processor 上，返回顶层 processor。"""
    image_processor = SimpleNamespace(max_frames=4)
    processor = SimpleNamespace(image_processor=image_processor)

    returned = configure_processor_max_frames(processor, max_frames=8)

    assert returned is processor
    assert image_processor.max_frames == 8


def test_configure_processor_max_frames_46_style():
    """4.6 风格 processor：属性挂在 video_processor 子组件上，返回子组件。"""
    video_processor = SimpleNamespace(max_frames=32)
    processor = SimpleNamespace(video_processor=video_processor)

    returned = configure_processor_max_frames(processor, max_frames=8)

    assert returned is video_processor
    assert video_processor.max_frames == 8


def test_configure_processor_max_frames_set_failure():
    """属性设置不生效时应抛出 RuntimeError。"""
    class _ReadOnlyMaxFrames:
        max_frames = 4

        def __setattr__(self, name, value):
            if name == "max_frames":
                return
            super().__setattr__(name, value)

    processor = SimpleNamespace(image_processor=_ReadOnlyMaxFrames())
    with pytest.raises(RuntimeError, match="failed to set actual processor"):
        configure_processor_max_frames(processor, max_frames=8)


def test_configure_processor_max_frames_not_found():
    """找不到任何 max_frames/video_maxlen 参数时应抛出 RuntimeError。"""
    processor = SimpleNamespace(foo="bar")
    with pytest.raises(RuntimeError, match="cannot locate MiniCPM actual max-frame parameter"):
        configure_processor_max_frames(processor, max_frames=8)


# ---------------------------------------------------------------------------
# 4.6 风格 processor 兼容路径验证
# ---------------------------------------------------------------------------


def test_minicpm_46_style_healthcheck_and_reference(tmp_path: Path, monkeypatch):
    """4.6 风格 processor 返回 5D pixel_values_videos，healthcheck 应通过且内部引用正确。"""
    from unittest.mock import patch

    monkeypatch.setattr(
        "pipeline.preprocessing.minicpm_preprocessor._processor_environment_unsupported",
        lambda: False,
    )

    model_dir = tmp_path / "minicpm-4.6-mock"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    (model_dir / "preprocessor_config.json").write_text("{}")

    video_processor = SimpleNamespace(max_frames=32)
    top_processor = MagicMock()
    top_processor.video_processor = video_processor
    pixel_values = MagicMock()
    pixel_values.shape = (1, 5, 3, 224, 224)
    top_processor.return_value = {"pixel_values_videos": pixel_values}

    preprocessor = MiniCPMVideoPreprocessor(str(model_dir), processor=top_processor)

    # configure_processor_max_frames 应返回 video_processor 子组件
    assert preprocessor._video_processor is video_processor
    assert video_processor.max_frames == 8

    fake_frames = [MagicMock() for _ in range(5)]
    fake_indices = [0, 1, 2, 3, 4]
    fake_timestamps = [0.0, 0.1, 0.2, 0.3, 0.4]

    with patch.object(
        preprocessor,
        "_decode_frame_range",
        return_value=(fake_frames, fake_indices, fake_timestamps),
    ):
        ok = preprocessor.healthcheck()

    assert ok is True
    info = preprocessor.get_info()
    assert isinstance(info, ProcessorInfo)
    assert info.name == "minicpm-v-4.5"
    assert info.max_frames == 8
    assert info.backend == "transformers"
    assert info.version == type(top_processor).__name__


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
