from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.scripts.dataset_manager import (
    VIDEO_ANOMALY_KIND_PRESENCE_UNKNOWN,
    VIDEO_ANOMALY_KIND_TIME_UNKNOWN,
    _parse_frame_rate,
    _to_float,
    build_test_manifest_sha256,
    build_video_meta,
    compute_rare_pool,
    stratified_split,
    write_json,
)


def _make_records(n: int) -> list[dict]:
    """构造可用于 stratified_split 的伪 video_meta 记录。"""
    types = [
        "韧性断裂",
        "脆性断裂",
        "界面脱粘",
        "齐根断裂",
        "爆炸性断裂",
        "半脆半韧断裂",
        "界面脱粘、齐根断裂",
        "未断裂",
        "未夹紧",
        "视频异常",
    ]
    records = []
    for i in range(n):
        ftype = types[i % len(types)]
        loc = "inside_gauge" if i % 10 < 7 else "outside_gauge"
        loc_canonical = loc
        if ftype in {"未断裂", "未夹紧", "视频异常"}:
            loc = "N/A"
            loc_canonical = None
        records.append(
            {
                "video_id": f"video_{i:04d}",
                "type": ftype,
                "location": loc,
                "location_canonical": loc_canonical,
                "has_fracture": ftype not in {"未断裂", "未夹紧", "视频异常"},
                "is_abnormal": ftype in {"未夹紧", "视频异常"},
                "has_fracture_canonical": ftype not in {"未断裂", "未夹紧", "视频异常"},
            }
        )
    return records


def _unwrap(splits):
    """stratified_split 返回 (splits, decision_log)，测试只关心 splits。"""
    return splits[0] if isinstance(splits, tuple) else splits


def test_stratified_split_test_ratio_is_around_20_percent():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))
    total = len(records)
    test_ratio = len(splits["test"]) / total
    assert 0.15 <= test_ratio <= 0.25, f"test ratio {test_ratio} 不在 20% 附近"


def test_stratified_split_folds_are_disjoint_and_cover_all():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))

    all_ids = {r["video_id"] for r in records}
    test_ids = set(splits["test"])
    train_val_ids: set[str] = set()

    for i in range(3):
        train_ids = set(splits[f"fold_{i}_train"])
        val_ids = set(splits[f"fold_{i}_val"])
        assert train_ids & val_ids == set(), f"fold {i} train/val 有重叠"
        train_val_ids.update(train_ids, val_ids)

    assert test_ids & train_val_ids == set(), "test 与 train/val 有重叠"
    assert test_ids | train_val_ids == all_ids, "划分未覆盖全部视频"


def test_stratified_split_train_larger_than_val():
    records = _make_records(100)
    splits = _unwrap(stratified_split(records, test_ratio=0.2, n_folds=3, seed=42))
    for i in range(3):
        assert len(splits[f"fold_{i}_train"]) > len(splits[f"fold_{i}_val"])


def _make_records_with_rare() -> list[dict]:
    """构造包含稀有断裂类（<=2 视频）的记录。"""
    records: list[dict] = []
    # 常见类：韧性断裂 10 个
    for i in range(10):
        records.append(
            {
                "video_id": f"common_{i:03d}",
                "type": "韧性断裂",
                "location": "inside_gauge",
                "location_canonical": "inside_gauge",
                "has_fracture": True,
                "is_abnormal": False,
                "has_fracture_canonical": True,
            }
        )
    # 稀有类 A：2 视频
    for i in range(2):
        records.append(
            {
                "video_id": f"rare_a_{i:03d}",
                "type": "爆炸性断裂",
                "location": "inside_gauge",
                "location_canonical": "inside_gauge",
                "has_fracture": True,
                "is_abnormal": False,
                "has_fracture_canonical": True,
            }
        )
    # 稀有类 B：1 视频
    records.append(
        {
            "video_id": "rare_b_000",
            "type": "半脆半韧断裂",
            "location": "outside_gauge",
            "location_canonical": "outside_gauge",
            "has_fracture": True,
            "is_abnormal": False,
            "has_fracture_canonical": True,
        }
    )
    # 负样本：5 视频
    for i in range(5):
        records.append(
            {
                "video_id": f"neg_{i:03d}",
                "type": "未断裂",
                "location": "N/A",
                "location_canonical": None,
                "has_fracture": False,
                "is_abnormal": False,
                "has_fracture_canonical": False,
            }
        )
    return records


def test_compute_rare_pool_finds_low_frequency_fracture_types():
    records = _make_records_with_rare()
    rare_pool = compute_rare_pool(records)
    assert sorted(rare_pool) == ["rare_a_000", "rare_a_001", "rare_b_000"]


def test_stratified_split_rare_pool_only_in_train():
    records = _make_records_with_rare()
    splits, decision_log = stratified_split(records, test_ratio=0.2, n_folds=3, seed=42)
    rare_pool = set(decision_log["rare_pool"])
    assert rare_pool, "应有稀有池"

    for i in range(3):
        train_ids = set(splits[f"fold_{i}_train"])
        val_ids = set(splits[f"fold_{i}_val"])
        assert rare_pool <= train_ids, f"fold {i} 训练集应包含全部稀有池"
        assert not (rare_pool & val_ids), f"fold {i} 验证集不应包含稀有池"

    assert not (rare_pool & set(splits["test"])), "测试集不应包含稀有池"


# ---------------------------------------------------------------------------
# v2 五类训练语义
# ---------------------------------------------------------------------------


def _make_annotation_row(
    video_id: str,
    has_fracture: bool | None,
    is_abnormal: bool,
    ftype: str,
    location: str | None,
) -> dict:
    return {
        "id": video_id,
        "video_path": f"data/01_videos/{video_id}.mp4",
        "断裂时间点": "",
        "断裂模式": ftype,
        "材料类型": "金属",
        "清晰度": "480P",
        "断裂位置": location if location is not None else "",
        "断裂帧数": "",
        "视频时长": "",
        "视频帧率": "",
        "视频总帧数": "",
        "has_fracture": has_fracture,
        "is_abnormal": is_abnormal,
    }


def test_five_semantics_confirmed_fracture_time_reliable(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_fracture", has_fracture=True, is_abnormal=False,
                ftype="韧性断裂", location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["has_fracture_canonical"] is True
    assert rec["type"] == "韧性断裂"
    assert rec["location_canonical"] == "inside_gauge"
    assert rec["is_abnormal_canonical"] is False
    assert rec["video_anomaly_kind"] is None
    assert rec["event_time_reliable"] is True
    assert rec["is_label_conflict"] is False


def test_five_semantics_confirmed_no_fracture(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_no", has_fracture=False, is_abnormal=False,
                ftype="未断裂", location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["has_fracture_canonical"] is False
    assert rec["type"] == "未断裂"
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is False
    assert rec["video_anomaly_kind"] is None
    assert rec["event_time_reliable"] is False


def test_five_semantics_not_clamped(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_clamp", has_fracture=False, is_abnormal=True,
                ftype="未夹紧", location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["has_fracture_canonical"] is False
    assert rec["type"] == "未夹紧"
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is True
    assert rec["video_anomaly_kind"] is None
    assert rec["event_time_reliable"] is False


def test_five_semantics_video_anomaly_presence_unknown(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_presence", has_fracture=False, is_abnormal=True,
                ftype="视频异常", location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["has_fracture_canonical"] is None
    assert rec["type"] == "视频异常"
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is True
    assert rec["video_anomaly_kind"] == VIDEO_ANOMALY_KIND_PRESENCE_UNKNOWN
    assert rec["event_time_reliable"] is False


def test_five_semantics_video_anomaly_time_unknown(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_time", has_fracture=True, is_abnormal=True,
                ftype="视频异常", location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["has_fracture_canonical"] is True
    assert rec["type"] == "视频异常"
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is True
    assert rec["video_anomaly_kind"] == VIDEO_ANOMALY_KIND_TIME_UNKNOWN
    assert rec["event_time_reliable"] is False


def test_no_fracture_forces_is_abnormal_canonical_false(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "v_no_conflict", has_fracture=False, is_abnormal=True,
                ftype="未断裂", location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, _ = build_video_meta(df, Path("data/01_videos"))
    rec = records[0]
    assert rec["is_abnormal_canonical"] is False
    assert rec["is_label_conflict"] is True
    assert rec["label_governance_reason"] is not None


def test_build_test_manifest_sha256_is_stable():
    splits = {"test": ["c", "a", "b"], "fold_0_train": ["x"]}
    manifest = build_test_manifest_sha256(splits)
    assert manifest["count"] == 3
    assert manifest["test_video_ids"] == ["a", "b", "c"]
    assert len(manifest["sha256"]) == 64
    # 排序稳定性
    manifest2 = build_test_manifest_sha256({"test": ["a", "b", "c"]})
    assert manifest["sha256"] == manifest2["sha256"]


# ---------------------------------------------------------------------------
# 真实产物检查
# ---------------------------------------------------------------------------

VIDEO_META_PATH = ROOT / "data" / "07_metadata" / "video_meta.json"
SPLITS_DIR = ROOT / "data" / "05_splits"
METADATA_DIR = ROOT / "data" / "07_metadata"
DECISION_LOG_PATH = METADATA_DIR / "stratified_split_decision_log.json"
TEST_MANIFEST_PATH = METADATA_DIR / "test_manifest_sha256.json"

TIME_UNKNOWN_VIDEOS = {
    "video_0045",
    "video_0049",
    "video_0078",
    "video_0083",
    "video_0094",
    "video_0096",
    "video_0107",
}


@pytest.mark.skipif(not VIDEO_META_PATH.exists(), reason="video_meta.json 不存在")
def test_time_unknown_videos_keep_true_canonical():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    by_id = {r["video_id"]: r for r in meta}
    for vid in TIME_UNKNOWN_VIDEOS:
        rec = by_id[vid]
        assert rec["type"] == "视频异常", f"{vid} 应为视频异常"
        assert rec["has_fracture"] is True, f"{vid} CSV 原始 has_fracture 必须保留"
        assert rec["has_fracture_canonical"] is True, f"{vid} 时间不可靠异常 canonical 应为 True"
        assert rec["video_anomaly_kind"] == VIDEO_ANOMALY_KIND_TIME_UNKNOWN
        assert rec["location_canonical"] is None
        assert rec["event_time_reliable"] is False


@pytest.mark.skipif(not VIDEO_META_PATH.exists(), reason="video_meta.json 不存在")
def test_no_fracture_videos_are_not_abnormal_canonical():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    for rec in meta:
        if rec["type"] == "未断裂":
            assert rec["is_abnormal_canonical"] is False, rec["video_id"]


@pytest.mark.skipif(
    not DECISION_LOG_PATH.exists(), reason="分层决策日志不存在"
)
def test_real_split_decision_log_in_metadata_dir():
    data = json.loads(DECISION_LOG_PATH.read_text(encoding="utf-8"))
    assert "rare_pool" in data
    assert "method" in data
    assert data.get("method") == "stratified_split_with_rare_pool"


@pytest.mark.skipif(
    not TEST_MANIFEST_PATH.exists(), reason="测试清单不存在"
)
def test_real_test_manifest_has_sha256():
    data = json.loads(TEST_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "sha256" in data
    assert "test_video_ids" in data
    assert len(data["sha256"]) == 64
    assert data["test_video_ids"] == sorted(data["test_video_ids"])


@pytest.mark.skipif(
    not (SPLITS_DIR / "test.json").exists(), reason="划分文件不存在"
)
def test_real_split_rare_pool_only_in_train():
    decision_log = json.loads(DECISION_LOG_PATH.read_text(encoding="utf-8"))
    rare_pool = set(decision_log.get("rare_pool", []))
    if not rare_pool:
        pytest.skip("稀有池为空，跳过")

    for i in range(3):
        train_ids = set(
            json.loads(
                (SPLITS_DIR / f"fold_{i}_train.json").read_text(encoding="utf-8")
            ).get("video_ids", [])
        )
        val_ids = set(
            json.loads(
                (SPLITS_DIR / f"fold_{i}_val.json").read_text(encoding="utf-8")
            ).get("video_ids", [])
        )
        assert rare_pool <= train_ids, f"fold {i} 训练集应包含全部稀有池"
        assert not (rare_pool & val_ids), f"fold {i} 验证集不应包含稀有池"

    test_ids = set(
        json.loads(
            (SPLITS_DIR / "test.json").read_text(encoding="utf-8")
        ).get("video_ids", [])
    )
    assert not (rare_pool & test_ids), "测试集不应包含稀有池"


@pytest.mark.skipif(
    not (SPLITS_DIR / "test.json").exists(), reason="划分文件不存在"
)
def test_real_splits_no_leakage_and_full_coverage():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    all_ids = {r["video_id"] for r in meta}

    splits: dict[str, set[str]] = {}
    for name in ["fold_0_train", "fold_0_val", "fold_1_train", "fold_1_val",
                 "fold_2_train", "fold_2_val", "test"]:
        path = SPLITS_DIR / f"{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        splits[name] = set(data.get("video_ids", []))

    test_ids = splits["test"]
    train_val_ids: set[str] = set()
    for name, ids in splits.items():
        if name == "test":
            continue
        assert not (ids & test_ids), f"{name} 与 test 存在视频泄漏"
        train_val_ids.update(ids)

    assert test_ids | train_val_ids == all_ids, "划分未覆盖全部视频"


@pytest.mark.skipif(
    not (SPLITS_DIR / "test.json").exists(), reason="划分文件不存在"
)
def test_real_split_test_ratio_around_20_percent():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    total = len(meta)
    test_data = json.loads((SPLITS_DIR / "test.json").read_text(encoding="utf-8"))
    test_count = len(test_data.get("video_ids", []))
    ratio = test_count / total
    assert 0.15 <= ratio <= 0.25, f"真实 test ratio={ratio:.2%} 不在 20% 附近"


@pytest.mark.skipif(
    not (SPLITS_DIR / "fold_0_train.json").exists(), reason="划分文件不存在"
)
def test_real_split_type_distribution_not_empty():
    meta = json.loads(VIDEO_META_PATH.read_text(encoding="utf-8"))
    by_id = {r["video_id"]: r for r in meta}

    for name in ["test", "fold_0_train", "fold_0_val"]:
        path = SPLITS_DIR / f"{name}.json"
        if not path.exists():
            continue
        ids = json.loads(path.read_text(encoding="utf-8")).get("video_ids", [])
        types = {by_id[vid]["type"] for vid in ids if vid in by_id}
        assert types, f"{name} 中没有任何 type"


# ---------------------------------------------------------------------------
# 标签治理 / canonical 字段单元测试
# ---------------------------------------------------------------------------


def test_canonical_preserved_for_video_anomaly_time_unknown(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_time_unknown",
                has_fracture=True,
                is_abnormal=True,
                ftype="视频异常",
                location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True, "CSV 原始 has_fracture 必须保留"
    assert rec["location"] == "N/A", "CSV 原始 location 必须保留"
    assert rec["has_fracture_canonical"] is True
    assert rec["video_anomaly_kind"] == VIDEO_ANOMALY_KIND_TIME_UNKNOWN
    assert rec["location_canonical"] is None
    assert rec["is_label_conflict"] is False
    assert rec["label_governance_reason"] is None


def test_canonical_preserved_for_video_anomaly_presence_unknown(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_presence_unknown",
                has_fracture=False,
                is_abnormal=False,
                ftype="视频异常",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is False
    assert rec["has_fracture_canonical"] is None
    assert rec["video_anomaly_kind"] == VIDEO_ANOMALY_KIND_PRESENCE_UNKNOWN
    assert rec["location_canonical"] is None


def test_canonical_preserved_for_non_fracture_type(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_bad_type",
                has_fracture=True,
                is_abnormal=False,
                ftype="未断裂",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True, "CSV 原始 has_fracture 必须保留"
    assert rec["type"] == "未断裂", "CSV 原始 type 必须保留"
    assert rec["has_fracture_canonical"] is False
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is False
    assert rec["is_label_conflict"] is True
    assert "type=未断裂但 CSV has_fracture=True" in rec["label_governance_reason"]


def test_canonical_equals_original_for_normal_fracture(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_normal",
                has_fracture=True,
                is_abnormal=False,
                ftype="韧性断裂",
                location="inside_gauge",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is True
    assert rec["has_fracture_canonical"] is True
    assert rec["location"] == "inside_gauge"
    assert rec["location_canonical"] == "inside_gauge"
    assert rec["is_abnormal_canonical"] is False
    assert rec["is_label_conflict"] is False
    assert rec["label_governance_reason"] is None


def test_canonical_equals_original_for_normal_negative(monkeypatch: pytest.MonkeyPatch):
    df = pd.DataFrame(
        [
            _make_annotation_row(
                "video_neg",
                has_fracture=False,
                is_abnormal=False,
                ftype="未断裂",
                location="N/A",
            )
        ]
    )
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["has_fracture"] is False
    assert rec["has_fracture_canonical"] is False
    assert rec["location_canonical"] is None
    assert rec["is_abnormal_canonical"] is False
    assert rec["is_label_conflict"] is False
    assert rec["label_governance_reason"] is None


# ---------------------------------------------------------------------------
# NaN / inf 健壮性
# ---------------------------------------------------------------------------


def test_to_float_rejects_nan_and_inf():
    assert _to_float(float("nan")) is None
    assert _to_float(float("inf")) is None
    assert _to_float(float("-inf")) is None
    assert _to_float("nan") is None
    assert _to_float("inf") is None
    assert _to_float("-inf") is None
    assert _to_float("3.14") == 3.14


def test_parse_frame_rate_rejects_nan_and_inf():
    assert _parse_frame_rate("nan") is None
    assert _parse_frame_rate("inf") is None
    assert _parse_frame_rate("-inf") is None
    assert _parse_frame_rate("NaN") is None
    assert _parse_frame_rate("1/0") is None
    assert _parse_frame_rate("0/0") is None
    assert _parse_frame_rate("30/1") == 30.0
    assert _parse_frame_rate("29.97") == 29.97


def test_build_video_meta_handles_nan_duration_and_fps(monkeypatch: pytest.MonkeyPatch):
    row = _make_annotation_row(
        "video_nan_meta",
        has_fracture=False,
        is_abnormal=False,
        ftype="未断裂",
        location="N/A",
    )
    row["视频时长"] = float("nan")
    row["视频帧率"] = float("nan")
    df = pd.DataFrame([row])
    monkeypatch.setattr("pipeline.scripts.dataset_manager._ffprobe", lambda path: {})
    records, warnings = build_video_meta(df, Path("data/01_videos"))
    assert len(records) == 1
    rec = records[0]
    assert rec["fps"] == 30.0
    assert rec["duration"] == 0.0
    assert rec["total_frames"] is None


def test_write_json_rejects_nan(tmp_path: Path):
    with pytest.raises(ValueError):
        write_json(tmp_path / "bad.json", {"value": float("nan")})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
