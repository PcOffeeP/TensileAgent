from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing import FrameMapping, ProcessorInfo
from pipeline.scripts.calibration import (
    _build_cases_for_video,
    _check_mapping_match,
    _check_order_match,
    _collect_split_video_ids,
    _compare_results,
    _pick_calibration_videos,
    _try_load_llama_factory_batch,
    _window_positions,
    build_calibration_cases,
)


# ===================================================================
# _pick_calibration_videos
# ===================================================================


def _make_meta_entry(
    video_id: str,
    duration: float,
    *,
    is_abnormal_canonical: bool = False,
    video_anomaly_kind: str | None = None,
    has_fracture_canonical: bool | None = None,
) -> dict:
    return {
        "video_id": video_id,
        "duration": duration,
        "is_abnormal_canonical": is_abnormal_canonical,
        "video_anomaly_kind": video_anomaly_kind,
        "has_fracture_canonical": has_fracture_canonical,
        "video_path": f"data/videos/{video_id}.mp4",
        "type": "tensile",
    }


def test_pick_empty_meta_returns_empty():
    result = _pick_calibration_videos({}, set())
    assert result == []


def test_pick_empty_available_ids_returns_empty():
    meta = {"v1": _make_meta_entry("v1", 30.0)}
    result = _pick_calibration_videos(meta, set())
    assert result == []


def test_pick_no_available_ids_match_meta_returns_empty():
    meta = {"v1": _make_meta_entry("v1", 30.0)}
    result = _pick_calibration_videos(meta, {"v2"})
    assert result == []


def test_pick_selects_from_each_category_duration_bucket():
    """各（类别, 时长桶）组合至少各选 n_per_category 个视频。"""
    meta = {
        # no_fracture - short
        "v1": _make_meta_entry("v1", 5.0),
        "v2": _make_meta_entry("v2", 5.0),
        "v3": _make_meta_entry("v3", 5.0),
        # no_fracture - medium
        "v4": _make_meta_entry("v4", 30.0),
        "v5": _make_meta_entry("v5", 30.0),
        # no_fracture - long
        "v6": _make_meta_entry("v6", 120.0),
        # fracture - short
        "v7": _make_meta_entry("v7", 8.0, has_fracture_canonical=True),
        "v8": _make_meta_entry("v8", 8.0, has_fracture_canonical=True),
        # abnormal - medium
        "v9": _make_meta_entry("v9", 45.0, is_abnormal_canonical=True),
    }
    available = set(meta.keys())
    result = _pick_calibration_videos(meta, available, n_per_category=2)

    assert "v1" in result
    assert "v2" in result
    assert "v4" in result
    assert "v5" in result
    assert "v6" in result
    assert "v7" in result
    assert "v8" in result
    assert "v9" in result
    # v3 is the 3rd short no-fracture, not selected (n_per_category=2)
    assert "v3" not in result


def test_pick_abnormal_via_anomaly_kind():
    """video_anomaly_kind 非空也归入 abnormal 类别。"""
    meta = {
        "v1": _make_meta_entry("v1", 30.0, video_anomaly_kind="cracks"),
        "v2": _make_meta_entry("v2", 30.0),  # normal
    }
    result = _pick_calibration_videos(meta, {"v1", "v2"}, n_per_category=1)
    assert "v1" in result


def test_pick_fracture_videos_are_selected():
    meta = {
        "v1": _make_meta_entry("v1", 30.0, has_fracture_canonical=True),
        "v2": _make_meta_entry("v2", 30.0),
    }
    result = _pick_calibration_videos(meta, {"v1", "v2"}, n_per_category=1)
    assert "v1" in result


def test_pick_fallback_to_at_least_three():
    """少于 3 个候选视频时，兜底逻辑生效。"""
    meta = {"v1": _make_meta_entry("v1", 5.0)}
    result = _pick_calibration_videos(meta, {"v1"}, n_per_category=2)
    assert len(result) == 1  # 只有 1 个不可用但仍返回


def test_pick_fallback_with_two_videos():
    """2 个视频也全部返回。"""
    meta = {
        "v1": _make_meta_entry("v1", 5.0),
        "v2": _make_meta_entry("v2", 30.0),
    }
    result = _pick_calibration_videos(meta, {"v1", "v2"}, n_per_category=2)
    assert len(result) == 2
    assert "v1" in result
    assert "v2" in result


def test_pick_duration_bucket_border():
    """时长桶边界：10s 以下 short，10-60 medium，60+ long。"""
    meta = {
        "v_short": _make_meta_entry("v_short", 9.99),
        "v_med": _make_meta_entry("v_med", 10.0),
        "v_long": _make_meta_entry("v_long", 60.0),
    }
    available = set(meta.keys())
    result = _pick_calibration_videos(meta, available, n_per_category=1)
    assert "v_short" in result
    assert "v_med" in result
    assert "v_long" in result


def test_pick_returns_sorted_unique_ids():
    """结果去重且排序。"""
    meta = {
        "v_b": _make_meta_entry("v_b", 5.0),
        "v_a": _make_meta_entry("v_a", 5.0),
    }
    result = _pick_calibration_videos(meta, {"v_b", "v_a"}, n_per_category=2)
    assert result == sorted(result)
    assert len(result) == len(set(result))


# ===================================================================
# _window_positions
# ===================================================================


def test_window_positions_no_event_time():
    """无 event_time 时仅返回 start/end/middle。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=None)
    assert set(positions.keys()) == {"start", "end", "middle"}


def test_window_positions_with_event_time():
    """有 event_time 时额外返回 around_event。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=30.0)
    assert set(positions.keys()) == {"start", "end", "middle", "around_event"}


def test_window_positions_start():
    """start 窗口：从 0 开始，持续 size 秒。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=None)
    start, end = positions["start"]
    assert start == 0.0
    assert end == 10.0


def test_window_positions_start_clamped():
    """start 窗口不超 duration。"""
    positions = _window_positions(duration=5.0, size=10.0, event_time=None)
    start, end = positions["start"]
    assert start == 0.0
    assert end == 5.0


def test_window_positions_end():
    """end 窗口：结束在 duration，长度 size。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=None)
    start, end = positions["end"]
    assert start == 50.0
    assert end == 60.0


def test_window_positions_end_clamped():
    """end 窗口若 size > duration 则起始为 0。"""
    positions = _window_positions(duration=5.0, size=10.0, event_time=None)
    start, end = positions["end"]
    assert start == 0.0
    assert end == 5.0


def test_window_positions_middle():
    """middle 窗口以 duration/2 居中。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=None)
    start, end = positions["middle"]
    assert start == 25.0
    assert end == 35.0


def test_window_positions_middle_near_start():
    """middle 窗口靠近开头时不越界。"""
    positions = _window_positions(duration=5.0, size=4.0, event_time=None)
    start, end = positions["middle"]
    assert start >= 0.0
    assert end <= 5.0
    # mid = 2.5, start = 0.5, end = 4.5
    assert start == 0.5
    assert end == 4.5


def test_window_positions_around_event():
    """around_event 以 event_time 居中。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=30.0)
    start, end = positions["around_event"]
    assert start == 25.0
    assert end == 35.0


def test_window_positions_around_event_near_start():
    """event_time 靠近开头时窗口从 0 开始。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=2.0)
    start, end = positions["around_event"]
    assert start == 0.0
    assert end == 10.0


def test_window_positions_around_event_near_end():
    """event_time 靠近结尾时窗口在结尾处保持 size 长度。"""
    positions = _window_positions(duration=60.0, size=10.0, event_time=58.0)
    start, end = positions["around_event"]
    assert start == 50.0
    assert end == 60.0


def test_window_positions_size_larger_than_duration():
    """size > duration 时各位置不越界。"""
    positions = _window_positions(duration=8.0, size=10.0, event_time=4.0)
    for name, (s, e) in positions.items():
        assert s >= 0.0
        assert e <= 8.0
        assert s < e


# ===================================================================
# _build_cases_for_video
# ===================================================================


def _make_rec(
    video_id: str,
    duration: float,
    *,
    event_time: float | None = None,
    video_path: str = "data/videos/test.mp4",
    type_: str = "tensile",
) -> dict:
    return {
        "video_id": video_id,
        "duration": duration,
        "event_time": event_time,
        "video_path": video_path,
        "type": type_,
    }


def test_build_cases_always_has_full_case():
    """始终包含一个 full 区间 case。"""
    rec = _make_rec("v001", 120.0)
    cases = _build_cases_for_video(rec)
    full = [c for c in cases if c["event_position"] == "full"]
    assert len(full) == 1
    assert full[0]["start_time"] == 0.0
    assert full[0]["end_time"] == 120.0
    assert full[0]["window_size"] == 120.0


def test_build_cases_full_case_attributes():
    """full case 包含全部必要字段。"""
    rec = _make_rec("v001", 120.0, video_path="data/v/test.mp4", type_="bending")
    cases = _build_cases_for_video(rec)
    full = cases[0]
    assert full["case_id"] == "v001_full"
    assert full["video_id"] == "v001"
    assert full["type"] == "bending"
    assert "video_path" in full


def test_build_cases_includes_all_sizes():
    """duration 足够时，包含 30s/10s/3s 各窗口。"""
    rec = _make_rec("v001", 120.0)
    cases = _build_cases_for_video(rec)
    sizes = [c["window_size"] for c in cases]
    assert 30 in sizes
    assert 10 in sizes
    assert 3 in sizes


def test_build_cases_skips_smaller_than_duration():
    """duration 小于窗口大小时，跳过该窗口。"""
    rec = _make_rec("v001", 5.0)  # 只够 3s
    cases = _build_cases_for_video(rec)
    window_sizes = [c["window_size"] for c in cases]
    assert 3 in window_sizes
    assert 10 not in window_sizes
    assert 30 not in window_sizes


def test_build_cases_has_all_positions_for_each_size():
    """每个窗口大小下包含 start/end/middle/around_event（如有 event_time）。"""
    rec = _make_rec("v001", 120.0, event_time=50.0)
    cases = _build_cases_for_video(rec)
    size_positions: dict[int, set[str]] = {}
    for c in cases:
        if c["event_position"] == "full":
            continue
        sz = c["window_size"]
        size_positions.setdefault(sz, set()).add(c["event_position"])

    for sz in (30, 10, 3):
        assert "start" in size_positions[sz]
        assert "end" in size_positions[sz]
        assert "middle" in size_positions[sz]
        assert "around_event" in size_positions[sz]


def test_build_cases_no_event_time_omits_around_event():
    """无 event_time 时，不生成 around_event 位置。"""
    rec = _make_rec("v001", 120.0, event_time=None)
    cases = _build_cases_for_video(rec)
    around = [c for c in cases if c["event_position"] == "around_event"]
    assert len(around) == 0


def test_build_cases_case_id_format():
    """case_id 遵循 `{video_id}_{size}s_{position}` 格式。"""
    rec = _make_rec("v001", 120.0, event_time=50.0)
    cases = _build_cases_for_video(rec)
    for c in cases:
        if c["event_position"] == "full":
            assert c["case_id"] == "v001_full"
        else:
            assert c["case_id"] == f"v001_{c['window_size']}s_{c['event_position']}"


def test_build_cases_start_end_times_are_valid():
    """所有 case 的 start_time < end_time。"""
    rec = _make_rec("v001", 120.0, event_time=50.0)
    cases = _build_cases_for_video(rec)
    for c in cases:
        assert c["start_time"] < c["end_time"], f"invalid for {c['case_id']}"
        assert c["start_time"] >= 0.0
        assert c["end_time"] <= 120.0


def test_build_cases_very_short_video():
    """极短视频（1s）只有 full case，没有子窗口。"""
    rec = _make_rec("v001", 1.0)
    cases = _build_cases_for_video(rec)
    assert len(cases) == 1
    assert cases[0]["event_position"] == "full"


# ===================================================================
# _compare_results / _check_order_match / _check_mapping_match
# ===================================================================


@pytest.fixture
def processor_info() -> ProcessorInfo:
    return ProcessorInfo(
        name="mock-ffmpeg-uniform",
        version="0.1.0",
        max_frames=8,
        backend="ffmpeg",
    )


@pytest.fixture
def adapter_frames() -> list[FrameMapping]:
    return [
        FrameMapping(input_index=0, original_frame=0, timestamp=0.0),
        FrameMapping(input_index=1, original_frame=15, timestamp=0.5),
        FrameMapping(input_index=2, original_frame=30, timestamp=1.0),
    ]


def _batch_frames_from_adapter(adapter: list[FrameMapping]) -> list[dict]:
    return [
        {
            "input_index": f.input_index,
            "original_frame": f.original_frame,
            "timestamp": f.timestamp,
        }
        for f in adapter
    ]


def _make_batch_result(
    adapter_frames: list[FrameMapping],
    *,
    processor_name: str = "0.1.0",
    max_frames: int = 8,
    frame_count: int | None = None,
) -> dict:
    return {
        "source": "mock-llama-factory",
        "error": "",
        "processor_name": processor_name,
        "max_frames": max_frames,
        "frame_count": frame_count if frame_count is not None else len(adapter_frames),
        "frames": _batch_frames_from_adapter(adapter_frames),
        "tensor_digest": "same-digest",
        "adapter_tensor_digest": "same-digest",
        "tensor_shape": [1, len(adapter_frames), 3, 2, 2],
        "adapter_tensor_shape": [1, len(adapter_frames), 3, 2, 2],
    }


# --- _check_order_match ---


def test_order_match_exact_match():
    af = [
        FrameMapping(0, 0, 0.0),
        FrameMapping(1, 15, 0.5),
    ]
    bf = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 15, "timestamp": 0.5},
    ]
    assert _check_order_match(af, bf) is True


def test_order_match_count_mismatch():
    af = [FrameMapping(0, 0, 0.0)]
    bf: list[dict] = []
    assert _check_order_match(af, bf) is False


def test_order_match_input_index_mismatch():
    af = [FrameMapping(0, 0, 0.0), FrameMapping(1, 15, 0.5)]
    bf = [
        {"input_index": 0, "original_frame": 0},
        {"input_index": 2, "original_frame": 15},  # mismatched index
    ]
    assert _check_order_match(af, bf) is False


def test_order_match_original_frame_mismatch():
    af = [FrameMapping(0, 0, 0.0), FrameMapping(1, 15, 0.5)]
    bf = [
        {"input_index": 0, "original_frame": 0},
        {"input_index": 1, "original_frame": 99},  # wrong frame
    ]
    assert _check_order_match(af, bf) is False


def test_order_match_empty_lists():
    assert _check_order_match([], []) is True


# --- _check_mapping_match ---


def test_mapping_match_checks_frame_and_timestamp():
    af = [FrameMapping(0, 0, 0.0), FrameMapping(1, 15, 0.5)]
    bf = [
        {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 15, "timestamp": 0.5},
    ]
    assert _check_mapping_match(af, bf) is True


def test_mapping_match_mismatch():
    af = [FrameMapping(0, 0, 0.0)]
    bf = [{"input_index": 0, "original_frame": 99}]
    assert _check_mapping_match(af, bf) is False


# --- _compare_results ---


def test_compare_all_pass(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    batch = _make_batch_result(adapter_frames)
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is True
    assert result["processor_version_match"] is True
    assert result["max_frames_match"] is True
    assert result["frame_count_match"] is True
    assert result["order_match"] is True
    assert result["mapping_match"] is True


def test_compare_processor_name_mismatch(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    batch = _make_batch_result(adapter_frames, processor_name="wrong-name")
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is False
    assert result["processor_version_match"] is False


def test_compare_rejects_same_frame_count_with_different_actual_tensor(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    batch = _make_batch_result(adapter_frames)
    batch["tensor_digest"] = "different-digest"

    result = _compare_results(processor_info, adapter_frames, batch)

    assert result["frame_count_match"] is True
    assert result["tensor_digest_match"] is False
    assert result["passed"] is False


def test_compare_max_frames_mismatch(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    batch = _make_batch_result(adapter_frames, max_frames=16)
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is False
    assert result["max_frames_match"] is False


def test_compare_frame_count_mismatch(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    batch = _make_batch_result(adapter_frames, frame_count=999)
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is False
    assert result["frame_count_match"] is False


def test_compare_order_mismatch(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    wrong_frames = [
        {"input_index": 9, "original_frame": 9},  # all wrong
        {"input_index": 8, "original_frame": 8},
        {"input_index": 7, "original_frame": 7},
    ]
    batch = _make_batch_result(adapter_frames)
    batch["frames"] = wrong_frames
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is False
    assert result["order_match"] is False
    assert result["mapping_match"] is False


def test_compare_mapping_mismatch_alone(
    processor_info: ProcessorInfo,
    adapter_frames: list[FrameMapping],
):
    """mapping 失败但 order 也失败（当前实现 mapping==order）。"""
    wrong_frames = [
        {"input_index": 0, "original_frame": 99},
        {"input_index": 1, "original_frame": 99},
        {"input_index": 2, "original_frame": 99},
    ]
    batch = _make_batch_result(adapter_frames)
    batch["frames"] = wrong_frames
    result = _compare_results(processor_info, adapter_frames, batch)
    assert result["passed"] is False
    assert result["mapping_match"] is False


def test_compare_empty_frames(
    processor_info: ProcessorInfo,
):
    adapter: list[FrameMapping] = []
    batch = _make_batch_result(adapter)
    result = _compare_results(processor_info, adapter, batch)
    assert result["passed"] is True


# ===================================================================
# build_calibration_cases  — 集成测试（mock 文件 IO）
# ===================================================================


SAMPLE_META = [
    {
        "video_id": "v001",
        "duration": 120.0,
        "event_time": 45.0,
        "video_path": "data/videos/v001.mp4",
        "type": "tensile",
        "is_abnormal_canonical": False,
        "video_anomaly_kind": None,
        "has_fracture_canonical": False,
    },
    {
        "video_id": "v002",
        "duration": 5.0,
        "event_time": None,
        "video_path": "data/videos/v002.mp4",
        "type": "bending",
        "is_abnormal_canonical": False,
        "video_anomaly_kind": None,
        "has_fracture_canonical": True,
    },
    {
        "video_id": "v003",
        "duration": 45.0,
        "event_time": 20.0,
        "video_path": "data/videos/v003.mp4",
        "type": "tensile",
        "is_abnormal_canonical": True,
        "video_anomaly_kind": None,
        "has_fracture_canonical": False,
    },
    {
        "video_id": "v004",
        "duration": 90.0,
        "event_time": 70.0,
        "video_path": "data/videos/v004.mp4",
        "type": "tensile",
        "is_abnormal_canonical": False,
        "video_anomaly_kind": "cracks",
        "has_fracture_canonical": False,
    },
]

SAMPLE_SPLITS = {
    "train": {"video_ids": ["v001", "v002", "v003", "v004"]},
    "test": {"video_ids": ["v001", "v003"]},
}


def test_build_calibration_cases_integration():
    """build_calibration_cases 集成测试：mock 文件 IO，验证返回格式与内容。"""
    meta_path = Path("/fake/meta.json")
    splits_dir = Path("/fake/splits")

    with (
        patch("pipeline.scripts.calibration._load_video_meta") as mock_load_meta,
        patch("pipeline.scripts.calibration._load_splits") as mock_load_splits,
        patch("pipeline.scripts.calibration._collect_split_video_ids") as mock_collect,
    ):
        mock_load_meta.return_value = {r["video_id"]: r for r in SAMPLE_META}
        mock_load_splits.return_value = SAMPLE_SPLITS
        mock_collect.return_value = {"v001", "v002", "v003", "v004"}

        cases = build_calibration_cases(meta_path, splits_dir)

    # 验证结果
    assert isinstance(cases, list)
    assert len(cases) > 0

    # 所有 case 都包含必要字段
    for c in cases:
        assert "case_id" in c
        assert "video_id" in c
        assert "start_time" in c
        assert "end_time" in c
        assert "window_size" in c
        assert "event_position" in c
        assert "video_path" in c

    # 每种视频至少有一个 case
    video_ids_in_cases = {c["video_id"] for c in cases}
    assert "v001" in video_ids_in_cases
    assert "v002" in video_ids_in_cases
    assert "v003" in video_ids_in_cases
    assert "v004" in video_ids_in_cases

    # 验证 v002（短视频，5s，无 event_time）只有 full 和 3s 窗口
    v002_cases = [c for c in cases if c["video_id"] == "v002"]
    v002_positions = {c["event_position"] for c in v002_cases}
    v002_case_ids = {c["case_id"] for c in v002_cases}
    assert "full" in v002_positions
    assert "around_event" not in v002_positions  # no event_time
    assert "v002_3s_start" in v002_case_ids
    # 5s >= 3s，所以有 3s 窗口
    v002_window_sizes = {c["window_size"] for c in v002_cases if c["event_position"] != "full"}
    assert 3 in v002_window_sizes
    assert 10 not in v002_window_sizes  # 5 < 10
    assert 30 not in v002_window_sizes  # 5 < 30

    # v003（abnormal，45s）应有 30s/10s/3s 窗口
    v003_cases = [c for c in cases if c["video_id"] == "v003"]
    v003_window_sizes = {c["window_size"] for c in v003_cases if c["event_position"] != "full"}
    assert 30 in v003_window_sizes
    assert 10 in v003_window_sizes
    assert 3 in v003_window_sizes
    # 有 event_time，所以有 around_event
    v003_positions = {c["event_position"] for c in v003_cases}
    assert "around_event" in v003_positions


def test_build_calibration_cases_no_videos_in_splits():
    """splits 中无视频 ID 时返回空列表。"""
    meta_path = Path("/fake/meta.json")
    splits_dir = Path("/fake/splits")

    with (
        patch("pipeline.scripts.calibration._load_video_meta") as mock_load_meta,
        patch("pipeline.scripts.calibration._load_splits") as mock_load_splits,
        patch("pipeline.scripts.calibration._collect_split_video_ids") as mock_collect,
    ):
        mock_load_meta.return_value = {r["video_id"]: r for r in SAMPLE_META}
        mock_load_splits.return_value = {"train": {"video_ids": []}}
        mock_collect.return_value = set()

        cases = build_calibration_cases(meta_path, splits_dir)

    assert cases == []


def test_build_calibration_cases_handles_missing_video_in_meta():
    """splits 引用了 meta 中不存在的 video_id，应被忽略。"""
    meta_path = Path("/fake/meta.json")
    splits_dir = Path("/fake/splits")

    with (
        patch("pipeline.scripts.calibration._load_video_meta") as mock_load_meta,
        patch("pipeline.scripts.calibration._load_splits") as mock_load_splits,
        patch("pipeline.scripts.calibration._collect_split_video_ids") as mock_collect,
    ):
        # splits 引用 v999，但 meta 中没有
        meta = {r["video_id"]: r for r in SAMPLE_META}
        mock_load_meta.return_value = meta
        mock_load_splits.return_value = {"train": {"video_ids": ["v001", "v999"]}}
        mock_collect.return_value = {"v001", "v999"}

        cases = build_calibration_cases(meta_path, splits_dir)

    # v999 不在 meta 中，应该被忽略
    video_ids = {c["video_id"] for c in cases}
    assert "v001" in video_ids
    assert "v999" not in video_ids


# ===================================================================
# run_calibration — 集成测试（mock preprocessor）
# ===================================================================


def test_run_calibration_basic():
    """run_calibration 使用 mock preprocessor 走通骨架。"""
    from pipeline.scripts.calibration import run_calibration
    from pipeline.preprocessing import MockVideoPreprocessor

    rec = _make_rec("v001", 30.0, event_time=10.0)
    cases = _build_cases_for_video(rec)

    # MockVideoPreprocessor 的 healthcheck 依赖 ffmpeg
    # 这里用一个 mock preprocessor 替代
    class FakePreprocessor:
        """纯内存 preprocessor，不依赖视频文件。"""

        def get_info(self):
            return ProcessorInfo(name="fake", version="0.0.0", max_frames=4, backend="test")

        def healthcheck(self):
            return True

        def sample(self, video_path, start_time, end_time):
            # 返回 2 个固定帧（不依赖真实视频文件）
            return [
                FrameMapping(input_index=0, original_frame=0, timestamp=0.0),
                FrameMapping(input_index=1, original_frame=1, timestamp=0.033),
            ]

        def fingerprint(self):
            return "fake-fingerprint"

    preprocessor = FakePreprocessor()
    report = run_calibration(preprocessor, cases)  # type: ignore[arg-type]

    assert report["total_cases"] == len(cases)
    # 因为 _try_load_llama_factory_batch 会抛异常回退到 mock fallback，
    # 而 fallback 的 frames 与 adapter frames 字段一致，
    # 所以比较应该通过
    assert report["processor_info"]["name"] == "fake"
    assert report["fingerprint"] == "fake-fingerprint"
    assert isinstance(report["all_passed"], bool)
    assert isinstance(report["passed_cases"], int)


def test_run_calibration_compares_the_same_continuous_clip(monkeypatch):
    from types import SimpleNamespace
    from pipeline.scripts import calibration

    frames = [FrameMapping(0, 0, 0.0), FrameMapping(1, 1, 0.5)]
    calls = []

    class FakeClipBuilder:
        def __init__(self, output_dir):
            pass

        def build_with_manifest(self, source, sample_range):
            calls.append(("clip", source, sample_range))
            return SimpleNamespace(
                path="same-clip.mp4",
                manifest=[
                    {"temp_index": 0, "original_frame": 30, "timestamp": 1.0},
                    {"temp_index": 1, "original_frame": 45, "timestamp": 1.5},
                ],
            )

    class FakePreprocessor:
        def get_info(self):
            return ProcessorInfo("minicpm-v-4.5", "ProcessorV46", 8, "test")

        def fingerprint(self):
            return "production"

        def sample(self, path, start, end):
            calls.append(("adapter", path, start, end))
            return frames

    def fake_batch(path, info, adapter_frames, model_name):
        calls.append(("batch", path))
        return {
            "processor_name": "ProcessorV46",
            "max_frames": 8,
            "frame_count": 2,
            "frames": [
                {"input_index": 0, "original_frame": 0, "timestamp": 0.0},
                {"input_index": 1, "original_frame": 1, "timestamp": 0.5},
            ],
            "tensor_digest": "same",
            "adapter_tensor_digest": "same",
            "tensor_shape": [1, 2, 3, 2, 2],
            "adapter_tensor_shape": [1, 2, 3, 2, 2],
        }

    monkeypatch.setattr(calibration, "FfmpegVideoClipBuilder", FakeClipBuilder)
    monkeypatch.setattr(calibration, "_try_load_llama_factory_batch", fake_batch)
    report = calibration.run_calibration(
        FakePreprocessor(),
        [{
            "case_id": "v_3s_middle",
            "video_id": "v",
            "video_path": "source.mp4",
            "start_time": 1.0,
            "end_time": 2.0,
            "window_size": 1.0,
            "event_position": "middle",
        }],
    )

    assert report["all_passed"] is True
    assert ("adapter", "same-clip.mp4", 0.0, 1.0) in calls
    assert ("batch", "same-clip.mp4") in calls
    assert report["cases"][0]["source_frame_mapping"][1]["original_frame"] == 45


def test_formal_calibration_cli_rejects_mock():
    from pipeline.scripts.calibration import _build_argparser

    with pytest.raises(SystemExit):
        _build_argparser().parse_args(["--preprocessor", "mock"])


# ===================================================================
# _try_load_llama_factory_batch — fail-closed paths
# ===================================================================


def _fixture_preprocessor_info() -> ProcessorInfo:
    return ProcessorInfo(name="mock-ffmpeg-uniform", version="0.1.0", max_frames=8, backend="ffmpeg")


def _fixture_adapter_frames() -> list[FrameMapping]:
    return [
        FrameMapping(input_index=0, original_frame=0, timestamp=0.0),
        FrameMapping(input_index=1, original_frame=15, timestamp=0.5),
        FrameMapping(input_index=2, original_frame=30, timestamp=1.0),
    ]


def test_try_load_llama_factory_batch_requires_llama_factory():
    info = _fixture_preprocessor_info()
    frames = _fixture_adapter_frames()
    with pytest.raises(RuntimeError, match="LLaMA-Factory is required"):
        _try_load_llama_factory_batch("dummy.mp4", info, frames)


def _make_mock_llamafactory_modules(broken_plugin=None):
    """创建假冒的 llamafactory 模块层级，避免 torch 依赖。"""
    import sys as _sys
    from unittest.mock import MagicMock

    mock_plugin = MagicMock()
    if broken_plugin is not None:
        mock_plugin.MiniCPMVPlugin = MagicMock(return_value=broken_plugin)
    else:
        mock_plugin.MiniCPMVPlugin = MagicMock()

    mock_data = MagicMock()
    mock_data.mm_plugin = mock_plugin

    mock_llamafactory = MagicMock()
    mock_llamafactory.data = mock_data

    _sys.modules["llamafactory"] = mock_llamafactory
    _sys.modules["llamafactory.data"] = mock_data
    _sys.modules["llamafactory.data.mm_plugin"] = mock_plugin


def _make_mock_transformers_modules():
    """创建假冒的 transformers 模块层级，避免真实导入。"""
    import sys as _sys
    from unittest.mock import MagicMock

    mock_auto = MagicMock()
    mock_transformers = MagicMock()
    mock_transformers.AutoProcessor = mock_auto

    _sys.modules["transformers"] = mock_transformers


def _make_mock_torch():
    """创建假冒的 torch 模块。"""
    import sys as _sys
    from unittest.mock import MagicMock
    if "torch" not in _sys.modules:
        _sys.modules["torch"] = MagicMock()


def _cleanup_mock_modules():
    """清理注入的所有 mock 模块。"""
    import sys as _sys
    for key in list(_sys.modules):
        if key.startswith("llamafactory") or key == "transformers" or key == "torch":
            del _sys.modules[key]


@pytest.fixture
def mock_llamafactory():
    """Fixture：注入 mock llamafactory + transformers + torch 模块。"""
    _make_mock_llamafactory_modules()
    _make_mock_transformers_modules()
    _make_mock_torch()
    yield
    _cleanup_mock_modules()


def test_try_load_llama_factory_batch_requires_transformers(mock_llamafactory):
    info = _fixture_preprocessor_info()
    frames = _fixture_adapter_frames()

    # 让 transformers 导入失败
    import builtins
    original_import = builtins.__import__

    def _side_effect(name, *args, **kwargs):
        if name == "transformers":
            raise ImportError("no transformers")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_side_effect), pytest.raises(
        RuntimeError, match="transformers is required"
    ):
        _try_load_llama_factory_batch("dummy.mp4", info, frames)


def test_try_load_llama_factory_batch_processor_load_fails_closed(mock_llamafactory):
    info = _fixture_preprocessor_info()
    frames = _fixture_adapter_frames()

    with patch(
        "transformers.AutoProcessor.from_pretrained", side_effect=OSError("model not found")
    ), pytest.raises(OSError, match="model not found"):
        _try_load_llama_factory_batch("dummy.mp4", info, frames, model_name="fake/model")


def test_try_load_llama_factory_batch_get_mm_inputs_fails_closed(mock_llamafactory):
    info = _fixture_preprocessor_info()
    frames = _fixture_adapter_frames()

    class FakeProcessor:
        __class__ = type("FakeProcessor", (), {})()

        def __init__(self):
            self.video_processor = type("VideoProcessor", (), {"max_frames": 32})()

    class BrokenPlugin:
        def _get_mm_inputs(self, **kwargs):
            raise RuntimeError("simulated error")

    # 先清理再注入带 broken_plugin 的 mock
    _cleanup_mock_modules()
    _make_mock_llamafactory_modules(broken_plugin=BrokenPlugin())
    _make_mock_transformers_modules()
    # 注入 mock torch
    import sys
    from unittest.mock import MagicMock
    sys.modules["torch"] = MagicMock()

    def fake_sample(self, *_args, **_kwargs):
        self.last_tensor_digest = "adapter-digest"
        self.last_tensor_shape = [1, len(frames), 3, 2, 2]
        return frames

    with patch(
        "transformers.AutoProcessor.from_pretrained", return_value=FakeProcessor()
    ), patch(
        "pipeline.scripts.calibration._probe_video", return_value={"duration": 1.0}
    ), patch(
        "pipeline.scripts.calibration.MiniCPMVideoPreprocessor.sample", new=fake_sample
    ), pytest.raises(RuntimeError, match="simulated error"):
        _try_load_llama_factory_batch("dummy.mp4", info, frames)

    _cleanup_mock_modules()


def test_try_load_llama_factory_batch_requires_explicit_mapping(mock_llamafactory):
    info = _fixture_preprocessor_info()
    frames = _fixture_adapter_frames()

    class FakeProcessor:
        __class__ = type("FakeProcessor", (), {})()

    import builtins
    original_import = builtins.__import__

    def _side_effect(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return original_import(name, *args, **kwargs)

    with (
        patch("transformers.AutoProcessor.from_pretrained", return_value=FakeProcessor()),
        patch("builtins.__import__", side_effect=_side_effect),
    ):
        with pytest.raises((RuntimeError, AttributeError)):
            _try_load_llama_factory_batch("dummy.mp4", info, frames)

    _cleanup_mock_modules()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
