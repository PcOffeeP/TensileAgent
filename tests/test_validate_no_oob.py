from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_no_oob as vnoob


class TestIsValidFractureBetween:
    def test_adjacent_interval_passes(self):
        assert vnoob._is_valid_fracture_between([5, 6], n=10) is True

    def test_first_adjacent_interval_passes(self):
        assert vnoob._is_valid_fracture_between([0, 1], n=10) is True

    def test_left_boundary_sentinel_fails(self):
        """[0, 0] 边界哨兵不再被接受。"""
        assert vnoob._is_valid_fracture_between([0, 0], n=10) is False

    def test_right_boundary_sentinel_fails(self):
        """[N-1, N-1] 边界哨兵不再被接受。"""
        assert vnoob._is_valid_fracture_between([9, 9], n=10) is False

    def test_non_adjacent_non_sentinel_fails(self):
        assert vnoob._is_valid_fracture_between([0, 2], n=10) is False
        assert vnoob._is_valid_fracture_between([3, 5], n=10) is False

    def test_same_index_not_at_boundary_fails(self):
        assert vnoob._is_valid_fracture_between([5, 5], n=10) is False

    def test_malformed_fails(self):
        assert vnoob._is_valid_fracture_between([1], n=10) is False
        assert vnoob._is_valid_fracture_between([1, 2, 3], n=10) is False


def test_main_skips_when_generated_metadata_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vnoob, "ROOT", tmp_path)
    monkeypatch.setattr(vnoob, "META_DIR", tmp_path / "metadata")

    assert vnoob.main() == 0
    captured = capsys.readouterr()
    assert "SKIP: generated subvideo metadata does not exist" in captured.out
