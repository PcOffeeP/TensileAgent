from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.preprocessing import FrameMapping
from pipeline.scripts import subvideo_builder as builder


def _frames(*originals: int) -> list[dict]:
    return [
        {"input_index": i, "original_frame": f, "timestamp": float(i)}
        for i, f in enumerate(originals)
    ]


class _FakePreprocessor:
    """用于测试的轻量预处理器，不依赖 ffmpeg。"""

    def __init__(self, mappings: list[list[FrameMapping]] | None = None) -> None:
        self.calls: list[tuple[str, float, float]] = []
        self._mappings = mappings
        self._call_count = 0

    def sample(self, video_path: str, start_time: float, end_time: float) -> list[FrameMapping]:
        self.calls.append((video_path, start_time, end_time))
        if self._mappings is not None:
            idx = min(self._call_count, len(self._mappings) - 1)
            self._call_count += 1
            return self._mappings[idx]
        # Return four ordered frames spanning the requested interval.
        step = (end_time - start_time) / 3
        return [
            FrameMapping(
                i,
                int(round((start_time + i * step) * 30)),
                round(start_time + i * step, 4),
            )
            for i in range(4)
        ]

    def fingerprint(self) -> str:
        return "fake:test:v1"

    def healthcheck(self) -> bool:
        return True

    def get_info(self):
        from pipeline.preprocessing import ProcessorInfo

        return ProcessorInfo(name="fake", version="v1", max_frames=4, backend="test")


def test_compute_fracture_between_exact_hit_middle_returns_left_interval():
    sampled = _frames(10, 20, 30, 40, 50)
    assert builder.compute_fracture_between(sampled, 30) == [1, 2]


def test_compute_fracture_between_exact_hit_first_is_illegal():
    """命中第一帧时无法构成合法 [i, i+1]，应返回 None。"""
    sampled = _frames(30, 40, 50)
    assert builder.compute_fracture_between(sampled, 30) is None


def test_compute_fracture_between_exact_hit_last_uses_left_interval():
    """命中最后一帧时，取左侧相邻区间 [N-2, N-1]。"""
    sampled = _frames(10, 20, 30)
    assert builder.compute_fracture_between(sampled, 30) == [1, 2]


def test_compute_fracture_between_normal_interval():
    sampled = _frames(10, 20, 30, 40)
    assert builder.compute_fracture_between(sampled, 25) == [1, 2]


def test_compute_fracture_between_left_out_of_bounds_is_illegal():
    sampled = _frames(20, 30, 40)
    assert builder.compute_fracture_between(sampled, 5) is None


def test_compute_fracture_between_right_out_of_bounds_is_illegal():
    sampled = _frames(10, 20, 30)
    assert builder.compute_fracture_between(sampled, 100) is None


def test_compute_fracture_between_none_event_frame():
    assert builder.compute_fracture_between(_frames(10, 20), None) is None


def test_compute_fracture_between_empty_frames():
    assert builder.compute_fracture_between([], 10) is None


def test_parse_fps_rejects_nan_and_inf():
    assert builder._parse_fps("nan") is None
    assert builder._parse_fps("NaN") is None
    assert builder._parse_fps("inf") is None
    assert builder._parse_fps("Infinity") is None
    assert builder._parse_fps("-inf") is None
    assert builder._parse_fps("-Infinity") is None
    assert builder._parse_fps("30/1") == 30.0
    assert builder._parse_fps("30000/1001") == 30000.0 / 1001.0
    assert builder._parse_fps("29.97") == 29.97


def test_subvideo_builder_write_json_rejects_nan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(builder, "_create_preprocessor", lambda *_args: _FakePreprocessor())
    video_meta = tmp_path / "video_meta.json"
    splits_dir = tmp_path / "splits"
    subvideo_dir = tmp_path / "subvideos"
    frame_dir = tmp_path / "frames"
    output_meta = tmp_path / "subvideos_meta.json"
    splits_dir.mkdir(parents=True, exist_ok=True)

    records = [
        {
            "video_id": "v001",
            "video_path": "data/01_videos/v001.mp4",
            "fps": 30.0,
            "total_frames": 300,
            "duration": 10.0,
            "has_fracture": False,
            "has_fracture_canonical": False,
            "is_abnormal": False,
            "type": "未断裂",
            "location": "N/A",
            "event_frame_original": None,
        }
    ]
    video_meta.write_text(json.dumps(records), encoding="utf-8")
    (splits_dir / "fold_0_train.json").write_text(
        json.dumps({"split": "train", "video_ids": ["v001"]}), encoding="utf-8"
    )

    monkeypatch.setattr(
        builder,
        "build_subvideos_for_record",
        lambda rec, split_info, *args, **kwargs: [{
            "subvideo_id": "v001_full",
            "source_video": "v001",
            "video_path": "03_subvideos/v001_full.mp4",
            "crop_type": "full_pos",
            "start_time": 0.0,
            "end_time": 10.0,
            "duration": 10.0,
            "actual_frame_mapping": [
                {"input_index": i, "original_frame": i, "timestamp": float(i)}
                for i in range(8)
            ],
            "fold_assignments": ["fold_0_train"],
            "has_fracture": True,
            "has_fracture_canonical": True,
            "type": "韧性断裂",
            "bad_value": float("nan"),
        }],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "subvideo_builder",
            "--video-meta",
            str(video_meta),
            "--splits-dir",
            str(splits_dir),
            "--subvideo-dir",
            str(subvideo_dir),
            "--frame-dir",
            str(frame_dir),
            "--output-meta",
            str(output_meta),
            "--preprocessor",
            "minicpm",
        ],
    )

    with pytest.raises(ValueError):
        builder.main()


def test_load_splits_only_reads_new_interval_files(tmp_path: Path):
    # 旧基线文件应被忽略
    (tmp_path / "stratified_3_fold_0.json").write_text(
        '{"video_ids": ["old_001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_val.json").write_text(
        '{"split": "val", "video_ids": ["v003"]}', encoding="utf-8"
    )
    (tmp_path / "test.json").write_text(
        '{"split": "test", "video_ids": ["v004"]}', encoding="utf-8"
    )

    mapping = builder.load_splits(tmp_path)
    assert "old_001" not in mapping
    assert mapping["v001"]["split"] == "train"
    assert mapping["v003"]["split"] == "val"
    assert mapping["v004"]["split"] == "test"
    assert "fold_assignments" in mapping["v001"]


def test_load_splits_fold_assignments_are_complete(tmp_path: Path):
    # v001 同时出现在 fold_0_train、fold_1_train、fold_1_val
    (tmp_path / "fold_0_train.json").write_text(
        '{"split": "train", "video_ids": ["v001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_0_val.json").write_text(
        '{"split": "val", "video_ids": ["v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_1_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_1_val.json").write_text(
        '{"split": "val", "video_ids": ["v001"]}', encoding="utf-8"
    )
    (tmp_path / "fold_2_train.json").write_text(
        '{"split": "train", "video_ids": ["v001", "v002"]}', encoding="utf-8"
    )
    (tmp_path / "fold_2_val.json").write_text(
        '{"split": "val", "video_ids": ["v002"]}', encoding="utf-8"
    )

    mapping = builder.load_splits(tmp_path)
    assert set(mapping["v001"]["fold_assignments"]) == {
        "fold_0_train",
        "fold_1_train",
        "fold_1_val",
        "fold_2_train",
    }
    # 存在 val 时，primary 选择 val
    assert mapping["v001"]["split"] == "val"


def test_build_subvideos_for_record_generates_all_classes_for_fracture(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0001",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "type": "韧性断裂",
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 100,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s, *args, **kwargs: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": "03_subvideos/{}_full.mp4".format(r["video_id"]),
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full_pos",
            "event_position_ratio": None,
            "has_fracture": True,
            "is_abnormal": False,
            "fracture_between": [0, 1],
            "type": r["type"],
            "location": r["location"],
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(
        builder, "build_focus_subvideos", lambda r, s, *args, **kwargs: [{"crop_type": "focus"}] * 3
    )
    monkeypatch.setattr(
        builder, "build_neg_before_after", lambda r, s, *args, **kwargs: [{"crop_type": "neg"}] * 2
    )

    result = builder.build_subvideos_for_record(rec, split_info)
    crop_types = [r["crop_type"] for r in result]
    assert crop_types.count("full_pos") == 1
    assert crop_types.count("focus") == 3
    assert crop_types.count("neg") == 2


def test_build_subvideos_for_record_abnormal_only_full(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0045",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": True,
        "type": "视频异常",
        "location": "N/A",
        "event_frame_original": 100,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s, *args, **kwargs: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": "03_subvideos/{}_full.mp4".format(r["video_id"]),
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full_anomaly_time_unknown",
            "event_position_ratio": None,
            "has_fracture": True,
            "is_abnormal": True,
            "fracture_between": None,
            "type": r["type"],
            "location": None,
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(builder, "build_focus_subvideos", lambda r, s, *args, **kwargs: [])
    monkeypatch.setattr(builder, "build_neg_before_after", lambda r, s, *args, **kwargs: [])

    result = builder.build_subvideos_for_record(rec, split_info)
    assert len(result) == 1
    assert result[0]["crop_type"].startswith("full")


def test_build_subvideos_for_record_non_fracture_only_full(
    monkeypatch: pytest.MonkeyPatch,
):
    rec = {
        "video_id": "video_0099",
        "has_fracture": False,
        "has_fracture_canonical": False,
        "is_abnormal": False,
        "type": "未断裂",
        "location": "N/A",
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": []}

    monkeypatch.setattr(
        builder,
        "build_full_subvideo",
        lambda r, s, *args, **kwargs: {
            "subvideo_id": f"{r['video_id']}_full",
            "source_video": r["video_id"],
            "video_path": "03_subvideos/{}_full.mp4".format(r["video_id"]),
            "frame_paths": [],
            "start_time": 0.0,
            "end_time": r["duration"],
            "duration": r["duration"],
            "crop_type": "full_neg",
            "event_position_ratio": None,
            "has_fracture": False,
            "is_abnormal": False,
            "fracture_between": None,
            "type": r["type"],
            "location": None,
            "source_type": r["type"],
            "source_location": r["location"],
            "fold": s.get("fold"),
            "split": s.get("split"),
            "fold_assignments": s.get("fold_assignments", []),
        },
    )
    monkeypatch.setattr(builder, "build_focus_subvideos", lambda r, s, *args, **kwargs: [])
    monkeypatch.setattr(builder, "build_neg_before_after", lambda r, s, *args, **kwargs: [])
    monkeypatch.setattr(builder, "build_non_fracture_clips", lambda r, s, *args, **kwargs: [])

    result = builder.build_subvideos_for_record(rec, split_info)
    assert len(result) == 1
    assert result[0]["crop_type"] == "full_neg"


def test_build_full_subvideo_preserves_original_and_outputs_canonical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """冲突视频的 full 子视频应保留原始标签，同时输出 canonical 字段。"""
    fake_video = tmp_path / "video_conflict.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "video_conflict",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": True,
        "type": "视频异常",
        "location": "inside_gauge",
        "location_canonical": None,
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 1000,
        "duration": 33.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "test", "fold": "test", "fold_assignments": []}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)
    monkeypatch.setattr(
        builder, "extract_sampled_frames", lambda path, out_dir, n, duration: []
    )

    sub = builder.build_full_subvideo(rec, split_info, preprocessor=_FakePreprocessor())
    assert sub is not None
    assert sub["has_fracture"] is True
    assert sub["has_fracture_canonical"] is True
    assert sub["type"] == "视频异常"
    assert sub["location"] is None
    assert sub["location_canonical"] is None
    assert sub["source_type"] == "视频异常"
    assert sub["source_location"] == "inside_gauge"
    assert sub["crop_type"] == "full_anomaly_time_unknown"


# ---------------------------------------------------------------------------
# v2 候选策略与选择
# ---------------------------------------------------------------------------


def test_candidates_for_confirmed_fracture_include_focus_and_negatives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """确认断裂且时间可靠应生成完整视频 + 聚焦 + 断裂前/后负样本。"""
    fake_video = tmp_path / "v_frac.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_frac",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 150,
        "event_time": 5.0,
        "fps": 30.0,
        "total_frames": 600,
        "duration": 20.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)
    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)
    monkeypatch.setattr(
        builder, "extract_sampled_frames", lambda path, out_dir, n, duration: []
    )

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    crop_types = [c["crop_type"] for c in candidates]
    assert any(c.startswith("full") for c in crop_types)
    assert any(c.startswith("focus_") for c in crop_types)
    assert any(c == "neg_before" for c in crop_types)
    assert any(c == "neg_after" for c in crop_types)


def test_candidates_for_no_fracture_include_fixed_negative_clips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """确认未断裂应生成完整视频 + 3s/10s/30s 前/中/后固定位置负样本。"""
    fake_video = tmp_path / "v_no.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_no",
        "type": "未断裂",
        "has_fracture": False,
        "has_fracture_canonical": False,
        "is_abnormal": False,
        "location": "N/A",
        "location_canonical": None,
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 600,
        "duration": 60.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)
    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    crop_types = [c["crop_type"] for c in candidates]
    assert any(c.startswith("full") for c in crop_types)
    assert all(c == "neg_position" or c.startswith("full") for c in crop_types)
    neg_ids = [c["subvideo_id"] for c in candidates if c["crop_type"] == "neg_position"]
    durations = sorted({int(re.search(r"_neg_pos_(\d+)s_", sid).group(1)) for sid in neg_ids})
    assert durations == [3, 10, 30]


def test_candidates_for_not_clamped_only_full(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """未夹紧只保留完整视频。"""
    fake_video = tmp_path / "v_clamp.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_clamp",
        "type": "未夹紧",
        "has_fracture": False,
        "has_fracture_canonical": False,
        "is_abnormal": True,
        "location": "N/A",
        "location_canonical": None,
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 200,
        "duration": 6.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    assert len(candidates) == 1
    assert candidates[0]["crop_type"] == "full_not_clamped"
    assert candidates[0]["type"] == "未夹紧"


def test_candidates_for_video_anomaly_only_full(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    """视频异常只保留完整视频，且 has_fracture_canonical 可为 null。"""
    fake_video = tmp_path / "v_anom.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_anom",
        "type": "视频异常",
        "has_fracture": False,
        "has_fracture_canonical": None,
        "is_abnormal": False,
        "location": "N/A",
        "location_canonical": None,
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 300,
        "duration": 10.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    assert len(candidates) == 1
    assert candidates[0]["has_fracture_canonical"] is None
    assert candidates[0]["type"] == "视频异常"


def test_test_split_videos_are_skipped(monkeypatch: pytest.MonkeyPatch):
    """测试集视频不生成任何子视频候选。"""
    rec = {
        "video_id": "v_test",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 150,
        "event_time": 5.0,
        "fps": 30.0,
        "total_frames": 600,
        "duration": 20.0,
        "video_path": "data/01_videos/v_test.mp4",
    }
    split_info = {"split": "test", "fold": "test", "fold_assignments": ["test"]}

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    assert candidates == []


def test_negative_clips_have_unified_labels(monkeypatch: pytest.MonkeyPatch):
    """负样本子视频统一标签为 has_fracture=false, type=未断裂, location=null。"""
    rec = {
        "video_id": "v_no",
        "type": "未断裂",
        "has_fracture": False,
        "has_fracture_canonical": False,
        "is_abnormal": False,
        "location": "N/A",
        "location_canonical": None,
        "event_frame_original": None,
        "fps": 30.0,
        "total_frames": 600,
        "duration": 20.0,
        "video_path": "data/01_videos/v_no.mp4",
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "copy_as_subvideo", lambda src, dst: None)
    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    candidates = builder.build_subvideos_for_record(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    for c in candidates:
        if c["crop_type"] == "neg_position":
            assert c["has_fracture_canonical"] is False
            assert c["type"] == "未断裂"
            assert c["location"] is None
            assert c["location_canonical"] is None
            assert c["fracture_between"] is None


def test_pre_event_negative_keeps_safe_gap(monkeypatch: pytest.MonkeyPatch):
    """断裂前负样本与事件保持 ≥1s 安全间隔。"""
    rec = {
        "video_id": "v_frac",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 150,
        "event_time": 5.0,
        "fps": 30.0,
        "total_frames": 900,
        "duration": 30.0,
        "video_path": "data/01_videos/v_frac.mp4",
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    candidates = builder.build_neg_before_after(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    pre_event = [c for c in candidates if c["crop_type"] == "neg_before"]
    assert pre_event
    for c in pre_event:
        assert c["end_time"] <= rec["event_time"] - 1.0 + 1e-6, c["subvideo_id"]


def test_post_event_hard_negative_frames_all_after_event(monkeypatch: pytest.MonkeyPatch):
    """断裂后困难负样本的所有采样帧必须晚于事件。"""
    rec = {
        "video_id": "v_frac",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 150,
        "event_time": 5.0,
        "fps": 30.0,
        "total_frames": 900,
        "duration": 30.0,
        "video_path": "data/01_videos/v_frac.mp4",
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    candidates = builder.build_neg_before_after(rec, split_info, generate_media=False, preprocessor=_FakePreprocessor())
    post_event = [c for c in candidates if c["crop_type"] == "neg_after"]
    assert post_event
    for c in post_event:
        for frame in c["sampled_frames"]:
            assert frame["timestamp"] > rec["event_time"], c["subvideo_id"]


def test_select_train_candidates_balances_pos_neg():
    """训练集选择后正负比例在 1:1 ~ 2:1 之间。"""
    candidates = []
    # 20 正
    for i in range(20):
        candidates.append({
            "subvideo_id": f"pos_{i:03d}",
            "source_video": f"v_{i:03d}",
            "fold_assignments": ["fold_0_train"],
            "crop_type": "full_pos",
            "has_fracture": True,
            "has_fracture_canonical": True,
            "type": "韧性断裂",
        })
    # 10 负
    for i in range(10):
        candidates.append({
            "subvideo_id": f"neg_{i:03d}",
            "source_video": f"v_n_{i:03d}",
            "fold_assignments": ["fold_0_train"],
            "crop_type": "neg_position",
            "has_fracture": False,
            "has_fracture_canonical": False,
            "type": "未断裂",
        })

    split_defs = {"fold_0_train": {f"v_{i:03d}" for i in range(20)} | {f"v_n_{i:03d}" for i in range(10)}}
    builder._select_train_candidates(candidates, split_defs, n_folds=1, seed=42)

    selected = [c for c in candidates if "fold_0_train" in c.get("selected_splits", [])]
    pos = [c for c in selected if c["has_fracture_canonical"] is True and c["type"] in builder.FRACTURE_TYPES]
    neg = [c for c in selected if not (c["has_fracture_canonical"] is True and c["type"] in builder.FRACTURE_TYPES)]
    ratio = len(pos) / len(neg) if neg else float("inf")
    assert 1.0 <= ratio <= 2.0, f"pos={len(pos)}, neg={len(neg)}, ratio={ratio}"


# ---------------------------------------------------------------------------
# start_frame / end_frame 一致性校验
# ---------------------------------------------------------------------------


def _load_subvideos(meta_path: Path) -> list[dict]:
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    return data.get("subvideos", []) if isinstance(data, dict) else data


@pytest.mark.skipif(
    not (ROOT / "data" / "07_metadata" / "subvideos_meta.json").exists(),
    reason="需要先生成 data/07_metadata/subvideos_meta.json 产物",
)
def test_subvideos_meta_has_start_end_frames():
    meta_path = ROOT / "data" / "07_metadata" / "subvideos_meta.json"
    subs = _load_subvideos(meta_path)
    assert subs
    for sub in subs:
        assert "start_frame" in sub, sub["subvideo_id"]
        assert "end_frame" in sub, sub["subvideo_id"]
        sf = sub["start_frame"]
        ef = sub["end_frame"]
        assert isinstance(sf, int), sub["subvideo_id"]
        assert isinstance(ef, int), sub["subvideo_id"]
        assert 0 <= sf < ef, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "07_metadata" / "subvideos_meta.json").exists(),
    reason="需要先生成 data/07_metadata/subvideos_meta.json 产物",
)
def test_subvideos_meta_positive_fracture_between_in_bounds_and_adjacent():
    """正样本的 fracture_between 必须是严格相邻区间 [i, i+1]，拒绝边界哨兵。"""
    meta_path = ROOT / "data" / "07_metadata" / "subvideos_meta.json"
    subs = _load_subvideos(meta_path)
    for sub in subs:
        if not sub.get("has_fracture"):
            continue
        # 视频异常（尤其是时间不可靠的异常）允许 has_fracture=True 但 fracture_between=None
        if sub.get("type") == "视频异常" or sub.get("is_abnormal"):
            continue
        fb = sub.get("fracture_between")
        assert fb is not None, sub["subvideo_id"]
        assert len(fb) == 2, sub["subvideo_id"]
        n = len(sub.get("sampled_frames") or [])
        assert 0 <= fb[0] < n, sub["subvideo_id"]
        assert 0 <= fb[1] < n, sub["subvideo_id"]
        assert fb[1] == fb[0] + 1, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "07_metadata" / "subvideos_meta.json").exists()
    or not (ROOT / "data" / "07_metadata" / "video_meta.json").exists(),
    reason="需要先生成 data/07_metadata/subvideos_meta.json 与 video_meta.json 产物",
)
def test_subvideos_meta_frame_bounds_consistent_with_time():
    meta_path = ROOT / "data" / "07_metadata" / "subvideos_meta.json"
    video_meta_path = ROOT / "data" / "07_metadata" / "video_meta.json"
    subs = _load_subvideos(meta_path)
    video_meta = {
        v["video_id"]: v
        for v in json.loads(video_meta_path.read_text(encoding="utf-8"))
    }
    for sub in subs:
        rec = video_meta[sub["source_video"]]
        fps = rec["fps"]
        total_frames = rec["total_frames"]
        sf = sub["start_frame"]
        ef = sub["end_frame"]
        assert 0 <= sf <= ef < total_frames, sub["subvideo_id"]
        assert abs(sub["start_time"] - sf / fps) < 0.5 / fps, sub["subvideo_id"]
        assert abs(sub["end_time"] - ef / fps) < 0.5 / fps, sub["subvideo_id"]


@pytest.mark.skipif(
    not (ROOT / "data" / "07_metadata" / "subvideos_meta.json").exists()
    or not (ROOT / "data" / "07_metadata" / "video_meta.json").exists(),
    reason="需要先生成 data/07_metadata/subvideos_meta.json 与 video_meta.json 产物",
)
def test_subvideos_meta_fracture_between_recalculation_consistent():
    """用 start_frame/end_frame 对应的时间区间反算 fracture_between，验证无 ±1 帧偏差。"""
    meta_path = ROOT / "data" / "07_metadata" / "subvideos_meta.json"
    video_meta_path = ROOT / "data" / "07_metadata" / "video_meta.json"
    subs = _load_subvideos(meta_path)
    video_meta = {
        v["video_id"]: v
        for v in json.loads(video_meta_path.read_text(encoding="utf-8"))
    }
    mismatches = []
    for sub in subs:
        if not sub.get("has_fracture"):
            continue
        # 视频异常（尤其是时间不可靠的异常）允许 fracture_between=None，无需反算
        if sub.get("type") == "视频异常" or sub.get("is_abnormal"):
            continue
        rec = video_meta[sub["source_video"]]
        event_frame = rec["event_frame_original"]
        if event_frame is None:
            continue
        sampled = sub.get("sampled_frames") or []
        recomputed = builder.compute_fracture_between(sampled, event_frame)
        if recomputed != sub["fracture_between"]:
            mismatches.append(
                (
                    sub["subvideo_id"],
                    sub["fracture_between"],
                    recomputed,
                    event_frame,
                    [f["original_frame"] for f in sampled],
                )
            )
    assert not mismatches, f"fracture_between 反算不一致: {mismatches[:5]}"


# ---------------------------------------------------------------------------
# 预处理适配层接入
# ---------------------------------------------------------------------------


def test_build_subvideos_for_record_populates_actual_frame_mapping_and_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """传入预处理器时，候选元数据应包含 actual_frame_mapping 与 processor_fingerprint。"""
    fake_video = tmp_path / "v_preproc.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_preproc",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 152,
        "event_time": 5.0,
        "fps": 30.0,
        "total_frames": 900,
        "duration": 30.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    preprocessor = _FakePreprocessor()
    candidates = builder.build_subvideos_for_record(
        rec, split_info, generate_media=False, preprocessor=preprocessor
    )
    assert preprocessor.calls
    for cand in candidates:
        assert cand.get("actual_frame_mapping") is not None
        assert cand["processor_fingerprint"] == "fake:test:v1"
        assert cand["processor_info"] == {
            "name": "fake",
            "version": "v1",
            "max_frames": 4,
            "backend": "test",
        }
        assert cand["sampled_frames"] == cand["actual_frame_mapping"]

    pos = [c for c in candidates if c.get("has_fracture") is True and c["type"] in builder.FRACTURE_TYPES]
    for c in pos:
        fb = c["fracture_between"]
        mapping = c["actual_frame_mapping"]
        assert fb is not None
        assert mapping[fb[0]]["original_frame"] < rec["event_frame_original"] <= mapping[fb[1]]["original_frame"]


def test_positive_candidate_excluded_when_fracture_between_unsatisfiable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """正样本若无法满足 sampled[i] < event <= sampled[i+1] 应被排除并记录原因。"""
    fake_video = tmp_path / "v_bad.mp4"
    fake_video.write_text("fake")
    rec = {
        "video_id": "v_bad",
        "type": "韧性断裂",
        "has_fracture": True,
        "has_fracture_canonical": True,
        "is_abnormal": False,
        "location": "inside_gauge",
        "location_canonical": "inside_gauge",
        "event_frame_original": 500,
        "event_time": 16.0,
        "fps": 30.0,
        "total_frames": 900,
        "duration": 30.0,
        "video_path": str(fake_video),
    }
    split_info = {"split": "train", "fold": "fold_0_train", "fold_assignments": ["fold_0_train"]}

    monkeypatch.setattr(builder, "crop_video", lambda src, dst, st, ed: None)

    # 预处理器始终返回远离 event_frame 的帧，±1s 调整后仍无法满足
    class StuckPreprocessor(_FakePreprocessor):
        def sample(self, video_path: str, start_time: float, end_time: float):
            self.calls.append((video_path, start_time, end_time))
            return [FrameMapping(i, 10 + i, 0.0) for i in range(4)]

    preprocessor = StuckPreprocessor()
    builder.EXCLUSIONS.clear()
    candidates = builder.build_subvideos_for_record(
        rec, split_info, generate_media=False, preprocessor=preprocessor
    )
    pos_ids = {c["subvideo_id"] for c in candidates if c.get("has_fracture")}
    # 所有聚焦正样本应被排除
    assert all("focus" not in sid for sid in pos_ids), pos_ids
    assert any(exc.get("reason") == "无法生成严格相邻的 fracture_between" for exc in builder.EXCLUSIONS)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
