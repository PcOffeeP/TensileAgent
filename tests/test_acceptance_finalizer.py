import pytest

from agent.acceptance_finalizer import _special_case_gate


def test_special_case_exact_gate_requires_expected_denominator() -> None:
    report = {
        "special_case_results": [
            {"special_case": f"case-{index}", "correct": True}
            for index in range(5)
        ]
    }
    assert _special_case_gate(report, "5/5") == {
        "actual": "5/5",
        "minimum": "5/5",
        "passed": True,
    }


def test_special_case_exact_gate_rejects_hidden_small_denominator() -> None:
    report = {
        "special_case_results": [
            {"special_case": f"case-{index}", "correct": True}
            for index in range(4)
        ]
    }
    assert _special_case_gate(report, "5/5")["passed"] is False


def test_special_case_exact_gate_rejects_invalid_spec() -> None:
    with pytest.raises(ValueError, match="N/N syntax"):
        _special_case_gate({"special_case_results": []}, "all")
