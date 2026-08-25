from __future__ import annotations

import sys

from pathlib import Path

import pytest

from agent import run as run_cli


class TestRunCliArgs:
    def test_help_includes_input_list(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["agent.run", "--help"])
        with pytest.raises(SystemExit) as cm:
            run_cli._parse_args()
        assert cm.value.code == 0
        assert "--input-list" in capsys.readouterr().out

    def test_video_source_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["agent.run", "--video", "data/vid.mp4"])
        args = run_cli._parse_args()
        assert args.video == "data/vid.mp4"
        assert args.videos_dir is None
        assert args.input_list is None

    def test_videos_dir_source_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["agent.run", "--videos-dir", "data/videos"])
        args = run_cli._parse_args()
        assert args.videos_dir == "data/videos"
        assert args.video is None
        assert args.input_list is None

    def test_input_list_source_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["agent.run", "--input-list", "data/list.txt"])
        args = run_cli._parse_args()
        assert args.input_list == "data/list.txt"
        assert args.video is None
        assert args.videos_dir is None

    def test_contract_version_can_be_pinned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "agent.run",
                "--video",
                "data/vid.mp4",
                "--contract-version",
                "tensile-vlm/v4.1",
            ],
        )
        args = run_cli._parse_args()
        assert args.contract_version == "tensile-vlm/v4.1"

    def test_video_and_input_list_are_mutually_exclusive(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            sys, "argv", ["agent.run", "--video", "a.mp4", "--input-list", "list.txt"]
        )
        with pytest.raises(SystemExit) as cm:
            run_cli._parse_args()
        assert cm.value.code == 2
        assert "--video" in capsys.readouterr().err


def test_write_jsonl_exits_with_error_on_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_mkdir(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    output_path = tmp_path / "missing" / "results.jsonl"
    with pytest.raises(SystemExit) as cm:
        run_cli._write_jsonl({"ok": True}, output_path)

    assert cm.value.code == 1
    err = capsys.readouterr().err
    assert "Failed to write results" in err
    assert "permission denied" in err


def test_write_jsonl_exits_with_error_on_serialization_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / "results.jsonl"

    with pytest.raises(SystemExit) as cm:
        run_cli._write_jsonl({"value": set([1, 2, 3])}, output_path)

    assert cm.value.code == 1
    err = capsys.readouterr().err
    assert "Failed to write results" in err


def test_make_event_writer_exits_on_mkdir_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_mkdir(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    events_dir = tmp_path / "data" / "08_runtime" / "events"
    with pytest.raises(SystemExit) as cm:
        run_cli._make_event_writer("20240101_000000", events_dir)

    assert cm.value.code == 1
    err = capsys.readouterr().err
    assert "Failed to create events directory" in err
    assert "permission denied" in err
