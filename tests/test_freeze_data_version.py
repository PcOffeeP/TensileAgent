from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.scripts.freeze_data_version import (
    _collect_config_hashes,
    _collect_git_commit,
    _sha256_file,
    main,
    run_freeze,
)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """创建包含最小 v2 产物与配置的临时项目目录。"""
    # 输入视频元数据
    video_meta = tmp_path / "data" / "07_metadata" / "video_meta.json"
    _write_json(
        video_meta,
        [{"video_id": f"video_{i:04d}"} for i in range(1, 111)],
    )

    # 划分文件
    splits_dir = tmp_path / "data" / "05_splits"
    splits_dir.mkdir(parents=True)
    for name in [
        "fold_0_train.json",
        "fold_0_val.json",
        "fold_1_train.json",
        "fold_1_val.json",
        "fold_2_train.json",
        "fold_2_val.json",
        "test.json",
    ]:
        _write_json(splits_dir / name, {"video_ids": ["video_0001"], "split": name.replace(".json", "")})

    # 产物目录
    merged_dir = tmp_path / "data" / "06_merged"
    merged_dir.mkdir(parents=True)
    sample = {
        "id": "video_0001_full",
        "videos": ["data/01_videos/video_0001.mp4"],
        "messages": [
            {"role": "assistant", "content": '{"has_fracture":true,"fracture_between":[6,7],"type":"韧性断裂","location":"inside_gauge","confidence":0.9}'}
        ],
        "source_video": "video_0001",
        "processor_fingerprint": "processor:v2:stable",
        "actual_frame_mapping": [{"input_index": i} for i in range(8)],
    }
    for name in ["fold_0_train.json", "fold_0_val.json", "fold_1_train.json", "fold_1_val.json", "fold_2_train.json", "fold_2_val.json"]:
        _write_json(merged_dir / name, [sample])
    _write_json(
        merged_dir / "samples_meta.json",
        {"total_samples": 6, "total_video_sources": 1, "total_positive": 6, "total_negative": 0},
    )
    _write_json(merged_dir / "test_inputs.json", [{"id": "video_0003", "video_id": "video_0003"}])

    # 配置文件
    config_files = [
        tmp_path / "finetune" / "dataset_info.json",
        tmp_path / "agent" / "config.yaml",
        tmp_path / "pyproject.toml",
    ]
    for p in config_files:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n", encoding="utf-8")

    # 子视频媒体目录
    subvideo_dir = tmp_path / "data" / "03_subvideos"
    subvideo_dir.mkdir(parents=True)
    (subvideo_dir / "placeholder.mp4").write_bytes(b"x")

    return tmp_path


class TestFieldPresence:
    def test_lock_contains_required_fields(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        lock_path = fake_project / "data_version_lock.json"
        config_files = [
            fake_project / "finetune" / "dataset_info.json",
            fake_project / "agent" / "config.yaml",
            fake_project / "pyproject.toml",
        ]
        lock = run_freeze(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            video_meta_path=fake_project / "data" / "07_metadata" / "video_meta.json",
            splits_dir=fake_project / "data" / "05_splits",
            subvideo_dir=fake_project / "data" / "03_subvideos",
            lock_path=lock_path,
            config_files=config_files,
            project_root=fake_project,
        )
        assert lock_path.exists()
        assert lock["version"] == "2.0.0"
        assert "code" in lock
        assert "config" in lock
        assert "processor" in lock
        assert "input_video_manifest" in lock
        assert "split_manifest" in lock
        assert "sample_manifest" in lock
        assert "statistics" in lock
        assert "disk_usage_bytes" in lock

    def test_input_video_count(self, fake_project: Path):
        lock = run_freeze(
            merged_dir=fake_project / "data" / "06_merged",
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            video_meta_path=fake_project / "data" / "07_metadata" / "video_meta.json",
            splits_dir=fake_project / "data" / "05_splits",
            subvideo_dir=fake_project / "data" / "03_subvideos",
            lock_path=fake_project / "lock.json",
            config_files=[],
            project_root=fake_project,
        )
        assert lock["input_video_manifest"]["count"] == 110
        assert lock["input_video_manifest"]["sha256"] is not None


class TestHashReproducibility:
    def test_same_files_produce_same_hashes(self, fake_project: Path):
        config_files = [
            fake_project / "finetune" / "dataset_info.json",
            fake_project / "agent" / "config.yaml",
            fake_project / "pyproject.toml",
        ]
        lock1 = run_freeze(
            merged_dir=fake_project / "data" / "06_merged",
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            video_meta_path=fake_project / "data" / "07_metadata" / "video_meta.json",
            splits_dir=fake_project / "data" / "05_splits",
            subvideo_dir=fake_project / "data" / "03_subvideos",
            lock_path=fake_project / "lock1.json",
            config_files=config_files,
            project_root=fake_project,
        )
        lock2 = run_freeze(
            merged_dir=fake_project / "data" / "06_merged",
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            video_meta_path=fake_project / "data" / "07_metadata" / "video_meta.json",
            splits_dir=fake_project / "data" / "05_splits",
            subvideo_dir=fake_project / "data" / "03_subvideos",
            lock_path=fake_project / "lock2.json",
            config_files=config_files,
            project_root=fake_project,
        )
        assert lock1["input_video_manifest"]["sha256"] == lock2["input_video_manifest"]["sha256"]
        assert lock1["split_manifest"]["sha256"] == lock2["split_manifest"]["sha256"]
        assert lock1["sample_manifest"]["sha256"] == lock2["sample_manifest"]["sha256"]
        assert lock1["config"]["combined_sha256"] == lock2["config"]["combined_sha256"]

    def test_config_hash_changes_when_content_changes(self, fake_project: Path):
        config_path = fake_project / "pyproject.toml"
        config_path.write_text("original", encoding="utf-8")
        h1 = _collect_config_hashes([config_path], fake_project)
        config_path.write_text("modified", encoding="utf-8")
        h2 = _collect_config_hashes([config_path], fake_project)
        assert h1["files"]["pyproject.toml"] != h2["files"]["pyproject.toml"]
        assert h1["combined_sha256"] != h2["combined_sha256"]


class TestGitCommit:
    def test_commit_hash_read(self, fake_project: Path, monkeypatch):
        def fake_run(cmd, **kwargs):
            mock = MagicMock()
            if "rev-parse" in cmd:
                mock.stdout = "abc123def456\n"
                mock.returncode = 0
            elif "status" in cmd:
                mock.stdout = "\n"
                mock.returncode = 0
            mock.stderr = ""
            return mock

        monkeypatch.setattr("pipeline.scripts.freeze_data_version.subprocess.run", fake_run)
        result = _collect_git_commit(fake_project)
        assert result["commit"] == "abc123def456"
        assert result["dirty"] is False

    def test_commit_hash_error_when_not_git_repo(self, fake_project: Path):
        result = _collect_git_commit(fake_project)
        assert result["commit"] is None
        assert "error" in result


class TestCli:
    def test_main_writes_lock(self, fake_project: Path, monkeypatch):
        def fake_run(cmd, **kwargs):
            mock = MagicMock()
            if "rev-parse" in cmd:
                mock.stdout = "cli123\n"
                mock.returncode = 0
            elif "status" in cmd:
                mock.stdout = "\n"
                mock.returncode = 0
            mock.stderr = ""
            return mock

        monkeypatch.setattr("pipeline.scripts.freeze_data_version.subprocess.run", fake_run)
        lock_path = fake_project / "cli_lock.json"
        rc = main(
            [
                "--merged-dir",
                str(fake_project / "data" / "06_merged"),
                "--subvideos-meta",
                str(fake_project / "data" / "07_metadata" / "subvideos_meta.json"),
                "--video-meta",
                str(fake_project / "data" / "07_metadata" / "video_meta.json"),
                "--splits-dir",
                str(fake_project / "data" / "05_splits"),
                "--subvideo-dir",
                str(fake_project / "data" / "03_subvideos"),
                "--lock",
                str(lock_path),
                "--project-root",
                str(fake_project),
            ]
        )
        assert rc == 0
        assert lock_path.exists()
