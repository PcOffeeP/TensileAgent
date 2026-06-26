from __future__ import annotations

import sys

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
