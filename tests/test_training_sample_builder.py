from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.scripts import training_sample_builder as builder


def _subvideo(
    video_id: str = "video_0001",
    has_fracture: bool | None = True,
    ftype: str | None = None,
    source_type: str | None = None,
    video_path: str | None = None,
) -> dict:
    """构造一条最小子视频元数据。"""
    ftype = ftype or ("韧性断裂" if has_fracture is True else "未断裂")
    source_type = source_type or ftype
    return {
        "subvideo_id": f"{video_id}_focus_3s_50pct",
        "source_video": video_id,
        "video_path": video_path or f"03_subvideos/{video_id}_focus_3s_50pct.mp4",
        "frame_paths": [f"04_frames/{video_id}_focus_3s_50pct/frame_{i:04d}.jpg" for i in range(8)],
        "start_time": 143.9,
        "end_time": 146.9,
        "start_frame": 4317,
        "end_frame": 4324,
        "duration": 3.0,
        "crop_type": "focus_3s",
        "event_position_ratio": 0.5,
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "fracture_between": [3, 4] if has_fracture is True else None,
        "type": ftype,
        "location": "inside_gauge" if has_fracture is True else "N/A",
        "location_canonical": "inside_gauge" if has_fracture is True else None,
        "source_type": source_type,
        "source_location": "inside_gauge",
        "actual_frame_mapping": [
            {"input_index": i, "original_frame": 4317 + i, "timestamp": round(143.9 + i / 30.0, 4)}
            for i in range(8)
        ],
        "processor_fingerprint": "minicpm-v-4.5:test:fingerprint",
        "fold": "fold_0_train",
        "split": "fold_0_train",
        "selection_reason": "focus_positive",
        "exclusion_reason": None,
    }


def _write_subvideos_meta(path: Path, subvideos: list[dict]) -> None:
    """将子视频元数据写入临时 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(subvideos, ensure_ascii=False), encoding="utf-8")


def _write_splits(splits_dir: Path, mapping: dict[str, list[str]]) -> None:
    """按 split 名称写入临时划分文件。"""
    splits_dir.mkdir(parents=True, exist_ok=True)
    for name, video_ids in mapping.items():
        (splits_dir / f"{name}.json").write_text(
            json.dumps({"video_ids": video_ids}, ensure_ascii=False),
            encoding="utf-8",
        )


def test_convert_subvideo_to_sample_sharegpt_format():
    sub = _subvideo(has_fracture=True)
    sample = builder.convert_subvideo_to_sample(sub)

    assert sample["id"] == sub["subvideo_id"]
    assert sample["videos"] == ["data/03_subvideos/video_0001_focus_3s_50pct.mp4"]
    assert len(sample["messages"]) == 3

    roles = [m["role"] for m in sample["messages"]]
    assert roles == ["system", "user", "assistant"]

    system_msg = sample["messages"][0]
    assert "材料拉伸试验视频分析助手" in system_msg["content"]

    user_msg = sample["messages"][1]
    assert "<video>" in user_msg["content"]
    assert "[143.9, 146.9]" in user_msg["content"]

    assistant_text = sample["messages"][2]["content"]
    assistant = json.loads(assistant_text)
    assert assistant["has_fracture"] is True
    assert assistant["fracture_between"] == [3, 4]
    assert assistant["type"] == "韧性断裂"
    assert assistant["location"] == "inside_gauge"
    assert assistant["confidence"] == pytest.approx(1.0)

    assert sample["has_fracture"] is True
    assert sample["fracture_between"] == [3, 4]
    assert sample["source_type"] == "韧性断裂"
    assert sample["source_location"] == "inside_gauge"
    assert sample["start_frame"] == sub["start_frame"]
    assert sample["end_frame"] == sub["end_frame"]


def test_convert_subvideo_preserves_data_videos_prefix():
    """子视频 video_path 为 data/01_videos/ 前缀时应原样透传。"""
    sub = _subvideo(
        video_id="video_0001",
        has_fracture=True,
        video_path="data/01_videos/video_0001.mp4",
    )
    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["videos"] == ["data/01_videos/video_0001.mp4"]


def test_convert_subvideo_prefixes_subvideo_dir():
    """子视频 video_path 缺少 data/ 前缀时应自动补全。"""
    sub = _subvideo(
        video_id="video_0001",
        has_fracture=True,
        video_path="03_subvideos/video_0001_focus_3s_50pct.mp4",
    )
    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["videos"] == ["data/03_subvideos/video_0001_focus_3s_50pct.mp4"]


def test_convert_subvideo_prefixes_frames_dir():
    """帧目录 video_path 缺少 data/ 前缀时应自动补全。"""
    sub = _subvideo(
        video_id="video_0001",
        has_fracture=True,
        video_path="04_frames/video_0001_focus_3s_50pct.mp4",
    )
    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["videos"] == ["data/04_frames/video_0001_focus_3s_50pct.mp4"]


def test_convert_subvideo_preserves_absolute_path():
    """绝对路径 video_path 应保持原样。"""
    sub = _subvideo(
        video_id="video_0001",
        has_fracture=True,
        video_path="/abs/path/to/video_0001.mp4",
    )
    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["videos"] == ["/abs/path/to/video_0001.mp4"]


def test_convert_negative_sample_has_null_fracture_between():
    sub = _subvideo(has_fracture=False)
    sample = builder.convert_subvideo_to_sample(sub)

    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["fracture_between"] is None
    assert assistant["type"] == "未断裂"
    assert assistant["location"] is None
    assert sample["fracture_between"] is None


def test_convert_assistant_json_has_exactly_five_fields():
    sub = _subvideo(has_fracture=True)
    sample = builder.convert_subvideo_to_sample(sub)
    assistant = json.loads(sample["messages"][2]["content"])
    assert set(assistant.keys()) == {"has_fracture", "fracture_between", "type", "location", "confidence"}
    assert isinstance(assistant["confidence"], float)
    assert assistant["confidence"] == pytest.approx(1.0)


def test_convert_presence_unknown_sample_has_null_has_fracture():
    sub = _subvideo(has_fracture=None, ftype="视频异常", source_type="视频异常")
    sample = builder.convert_subvideo_to_sample(sub)
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is None
    assert assistant["fracture_between"] is None
    assert assistant["type"] == "视频异常"
    assert assistant["location"] is None


def test_convert_time_unknown_anomaly_has_true_has_fracture_null_between():
    sub = _subvideo(has_fracture=True, ftype="视频异常", source_type="视频异常")
    sample = builder.convert_subvideo_to_sample(sub)
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is True
    assert assistant["fracture_between"] is None
    assert assistant["type"] == "视频异常"
    assert assistant["location"] is None


def test_compute_effective_frames_prefers_frame_paths():
    sub = _subvideo()
    assert builder.compute_effective_frames(sub) == len(sub["frame_paths"])


def test_build_split_samples_groups_by_source_video():
    sub1 = _subvideo("video_0001", has_fracture=True)
    sub2 = _subvideo("video_0002", has_fracture=False)
    split_ids = {
        "fold_0_train": {"video_0001"},
        "fold_0_val": {"video_0002"},
    }
    split_samples = builder.build_split_samples(
        [sub1, sub2], split_ids
    )
    assert len(split_samples["fold_0_train"]) == 1
    assert len(split_samples["fold_0_val"]) == 1
    assert split_samples["fold_0_train"][0]["source_video"] == "video_0001"


def test_build_all_outputs_valid_json_and_samples_meta(tmp_path):
    """build_all 在临时目录生成合法 JSON 与样本统计信息。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    sub1 = _subvideo("video_0001", has_fracture=True)
    sub2 = _subvideo("video_0002", has_fracture=False)
    _write_subvideos_meta(sub_meta, [sub1, sub2])
    _write_splits(
        splits_dir,
        {
            "fold_0_train": ["video_0001"],
            "fold_0_val": ["video_0002"],
        },
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
    )

    for name in builder.SPLIT_NAMES:
        if name == "test":
            continue
        path = out_dir / f"{name}.json"
        assert path.exists(), f"{path} 不存在"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        if data:
            first = data[0]
            assert "id" in first
            assert "videos" in first
            assert "messages" in first
            assert any(m["role"] == "system" for m in first["messages"])
            assert any(m["role"] == "user" for m in first["messages"])
            assert any(m["role"] == "assistant" for m in first["messages"])

    meta_path = out_dir / "samples_meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["total_samples"] > 0
    assert "splits" in meta
    assert all(name in meta["splits"] for name in builder.SPLIT_NAMES if name != "test")


def test_build_all_outputs_contain_metadata_fields(tmp_path):
    """生成的训练样本顶层必须包含 v2 metadata 字段。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    sub = _subvideo("video_0001", has_fracture=True)
    _write_subvideos_meta(sub_meta, [sub])
    _write_splits(splits_dir, {"fold_0_train": ["video_0001"]})

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
    )

    samples = json.loads((out_dir / "fold_0_train.json").read_text(encoding="utf-8"))
    assert samples
    sample = samples[0]
    assert sample["source_video"] == "video_0001"
    assert sample["source_type"] == "韧性断裂"
    assert sample["source_location"] == "inside_gauge"
    assert "actual_frame_mapping" in sample
    assert isinstance(sample["actual_frame_mapping"], list)
    assert sample["processor_fingerprint"] == sub["processor_fingerprint"]
    assert sample["selection_reason"] == "focus_positive"
    assert "exclusion_reason" in sample


@pytest.mark.parametrize("fingerprint", [None, "", "mock:test", "theoretical:v2"])
def test_convert_subvideo_rejects_non_production_fingerprint(fingerprint):
    sub = _subvideo("video_0001", has_fracture=True)
    sub["processor_fingerprint"] = fingerprint
    with pytest.raises(ValueError, match="fingerprint"):
        builder.convert_subvideo_to_sample(sub)


def test_build_all_outputs_test_artifacts_with_isolation(tmp_path):
    """测试集必须生成独立输入清单与真值，且训练样本不含测试视频。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"
    video_meta = tmp_path / "video_meta.json"

    train_sub = _subvideo("video_train", has_fracture=True)
    test_sub = _subvideo("video_test", has_fracture=False)
    _write_subvideos_meta(sub_meta, [train_sub, test_sub])
    _write_splits(
        splits_dir,
        {
            "fold_0_train": ["video_train"],
            "test": ["video_test"],
        },
    )
    video_meta.write_text(
        json.dumps(
            [
                {"video_id": "video_test", "has_fracture": False, "type": "未断裂"},
            ]
        ),
        encoding="utf-8",
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_meta_path=video_meta,
    )

    inputs_path = out_dir / "test_inputs.json"
    gt_path = out_dir / "test_ground_truth.json"
    assert inputs_path.exists()
    assert gt_path.exists()

    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    assert len(inputs) == 1
    assert inputs[0]["video_id"] == "video_test"
    assert len(gt) == 1
    assert gt[0]["video_id"] == "video_test"

    train_samples = json.loads((out_dir / "fold_0_train.json").read_text(encoding="utf-8"))
    assert all(s["source_video"] != "video_test" for s in train_samples)


def test_build_test_artifacts_uses_video_meta_path(tmp_path):
    """测试集输入清单应使用 video_meta.json 中的 video_path，而非硬编码前缀。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"
    video_meta = tmp_path / "video_meta.json"

    _write_subvideos_meta(sub_meta, [])
    _write_splits(splits_dir, {"test": ["video_test"]})
    video_meta.write_text(
        json.dumps(
            [
                {
                    "video_id": "video_test",
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "video_path": "03_subvideos/video_test_focus_3s.mp4",
                }
            ]
        ),
        encoding="utf-8",
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_meta_path=video_meta,
    )

    inputs = json.loads((out_dir / "test_inputs.json").read_text(encoding="utf-8"))
    assert len(inputs) == 1
    assert inputs[0]["video_path"] == "data/03_subvideos/video_test_focus_3s.mp4"


def test_build_test_artifacts_falls_back_to_default_prefix(tmp_path):
    """video_meta 缺少 video_path 时，测试集输入清单回退到 data/01_videos/。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"
    video_meta = tmp_path / "video_meta.json"

    _write_subvideos_meta(sub_meta, [])
    _write_splits(splits_dir, {"test": ["video_fallback"]})
    video_meta.write_text(
        json.dumps(
            [
                {"video_id": "video_fallback", "has_fracture": False, "type": "未断裂"},
            ]
        ),
        encoding="utf-8",
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
        video_meta_path=video_meta,
    )

    inputs = json.loads((out_dir / "test_inputs.json").read_text(encoding="utf-8"))
    assert len(inputs) == 1
    assert inputs[0]["video_path"] == "data/01_videos/video_fallback.mp4"


def test_build_all_outputs_contain_start_end_frames(tmp_path):
    """生成的训练样本顶层必须包含 start_frame / end_frame。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    sub = _subvideo("video_0001", has_fracture=True)
    _write_subvideos_meta(sub_meta, [sub])
    _write_splits(splits_dir, {"fold_0_train": ["video_0001"]})

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
    )

    for name in builder.SPLIT_NAMES:
        if name == "test":
            continue
        path = out_dir / f"{name}.json"
        assert path.exists(), f"{path} 不存在"
        samples = json.loads(path.read_text(encoding="utf-8"))
        for sample in samples:
            assert "start_frame" in sample, sample["id"]
            assert "end_frame" in sample, sample["id"]
            assert isinstance(sample["start_frame"], int)
            assert isinstance(sample["end_frame"], int)


def test_main_with_custom_paths():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        sub_meta = tmp_path / "subvideos_meta.json"
        splits_dir = tmp_path / "splits"
        out_dir = tmp_path / "out"
        splits_dir.mkdir()

        sub = _subvideo("video_0001", has_fracture=True)
        sub_meta.write_text(json.dumps([sub], ensure_ascii=False), encoding="utf-8")
        (splits_dir / "fold_0_train.json").write_text(
            json.dumps({"video_ids": ["video_0001"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        builder.build_all(
            subvideos_meta=sub_meta,
            splits_dir=splits_dir,
            output_dir=out_dir,
        )

        out_file = out_dir / "fold_0_train.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 1


# ---------------------------------------------------------------------------
# 异常/冲突样本处理断言
# ---------------------------------------------------------------------------

FRACTURE_TYPES = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
}


def test_time_unknown_anomaly_samples_keep_true_has_fracture(tmp_path):
    """时间不可靠视频异常的训练样本应保持 has_fracture=true、type=视频异常。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    subs = []
    for vid in ["video_tu_001", "video_tu_002"]:
        sub = _subvideo(vid, has_fracture=True, ftype="视频异常", source_type="视频异常")
        sub["fracture_between"] = None
        subs.append(sub)

    _write_subvideos_meta(sub_meta, subs)
    _write_splits(splits_dir, {"fold_0_train": ["video_tu_001", "video_tu_002"]})

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
    )

    samples = json.loads((out_dir / "fold_0_train.json").read_text(encoding="utf-8"))
    for sample in samples:
        assert sample["has_fracture"] is True
        assert sample["type"] == "视频异常"
        assert sample["location"] is None
        assistant = json.loads(sample["messages"][2]["content"])
        assert assistant["has_fracture"] is True
        assert assistant["fracture_between"] is None
        assert assistant["location"] is None


def test_no_positive_sample_with_non_fracture_type(tmp_path):
    """has_fracture=True 的样本 type 必须在 7 个断裂类中或视频异常时间不可靠。"""
    sub_meta = tmp_path / "subvideos_meta.json"
    splits_dir = tmp_path / "splits"
    out_dir = tmp_path / "out"

    positive = _subvideo("video_pos", has_fracture=True)
    positive["type"] = "韧性断裂"
    negative = _subvideo("video_neg", has_fracture=False)
    negative["type"] = "视频异常"
    negative["is_abnormal"] = True

    _write_subvideos_meta(sub_meta, [positive, negative])
    _write_splits(
        splits_dir,
        {
            "fold_0_train": ["video_pos"],
            "fold_0_val": ["video_neg"],
        },
    )

    builder.build_all(
        subvideos_meta=sub_meta,
        splits_dir=splits_dir,
        output_dir=out_dir,
    )

    for name in builder.SPLIT_NAMES:
        path = out_dir / f"{name}.json"
        if not path.exists():
            continue
        samples = json.loads(path.read_text(encoding="utf-8"))
        for sample in samples:
            if sample["has_fracture"] is True:
                assert sample["type"] in FRACTURE_TYPES | {"视频异常"}, (
                    f"{sample['id']} has_fracture=True 但 type={sample['type']}"
                )


def test_convert_subvideo_downgrades_inconsistent_positive():
    """子视频元数据中 has_fracture_canonical=False 时训练样本应被降级。"""
    sub = _subvideo("video_0045", has_fracture=True)
    sub["type"] = "视频异常"
    sub["location"] = "N/A"
    sub["location_canonical"] = "N/A"
    sub["fracture_between"] = [10, 11]
    sub["is_abnormal"] = True
    sub["has_fracture_canonical"] = False

    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["has_fracture"] is False
    assert sample["has_fracture_canonical"] is False
    assert sample["fracture_between"] is None
    assert sample["location"] is None
    assert sample["location_canonical"] is None
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["location"] is None


def test_convert_subvideo_prefers_canonical_over_original():
    """当 has_fracture 与 has_fracture_canonical 不一致时，训练样本使用 canonical。"""
    sub = _subvideo("video_conflict", has_fracture=True)
    sub["has_fracture"] = True  # CSV 原始值
    sub["has_fracture_canonical"] = False  # 治理后值
    sub["location"] = "inside_gauge"  # CSV 原始值
    sub["location_canonical"] = "N/A"  # 治理后值
    sub["type"] = "视频异常"
    sub["is_abnormal"] = True
    sub["fracture_between"] = [10, 11]

    sample = builder.convert_subvideo_to_sample(sub)
    assert sample["has_fracture"] is False
    assert sample["has_fracture_canonical"] is False
    assert sample["location"] is None
    assert sample["location_canonical"] is None
    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["has_fracture"] is False
    assert assistant["location"] is None


def test_assistant_fracture_between_matches_actual_frame_mapping():
    """assistant JSON 的 fracture_between 必须与 actual_frame_mapping 严格对应。"""
    sub = _subvideo("video_0001", has_fracture=True)
    sub["actual_frame_mapping"] = [
        {"input_index": i, "original_frame": 100 + i * 10, "timestamp": float(i)}
        for i in range(8)
    ]
    sub["fracture_between"] = [2, 3]
    sample = builder.convert_subvideo_to_sample(sub)

    assistant = json.loads(sample["messages"][2]["content"])
    assert assistant["fracture_between"] == [2, 3]
    mapping = sample["actual_frame_mapping"]
    assert 0 <= assistant["fracture_between"][0] < assistant["fracture_between"][1] < len(mapping)
    assert mapping[2]["original_frame"] < 125 <= mapping[3]["original_frame"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
