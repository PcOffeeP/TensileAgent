import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_delivery_bundle",
    ROOT / "scripts/validate_delivery_bundle.py",
)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_current_delivery_bundle_is_valid() -> None:
    report = validator.validate(ROOT)
    assert report["passed"] is True


def test_delivery_bundle_rejects_production_claim(monkeypatch) -> None:
    original_load = validator.load_object

    def load_with_claim(path: Path):
        value = original_load(path)
        if path.name == "agent_component.json":
            value = copy.deepcopy(value)
            value["capability"]["production_approved"] = True
        return value

    monkeypatch.setattr(validator, "load_object", load_with_claim)
    report = validator.validate(ROOT)
    assert "agent capability boundary is invalid" in report["errors"]


def test_performance_snapshot_cannot_block_intermediate_delivery(
    monkeypatch,
) -> None:
    original_load = validator.load_object

    def load_with_blocking_performance(path: Path):
        value = original_load(path)
        if path.name == "bundle.json":
            value = copy.deepcopy(value)
            value["performance_policy"]["blocks_intermediate_delivery"] = True
        return value

    monkeypatch.setattr(validator, "load_object", load_with_blocking_performance)
    report = validator.validate(ROOT)
    assert (
        "performance policy must remain record-only and non-blocking"
        in report["errors"]
    )


def test_delivery_gate_requires_every_chain_check(monkeypatch) -> None:
    original_load = validator.load_object

    def load_with_failed_chain(path: Path):
        value = original_load(path)
        if path.name == "bundle.json":
            value = copy.deepcopy(value)
            value["delivery_gate"]["checks"]["service_contract_verified"] = False
        return value

    monkeypatch.setattr(validator, "load_object", load_with_failed_chain)
    report = validator.validate(ROOT)
    assert "end-to-end delivery gate is incomplete" in report["errors"]


def test_core_step_results_keep_performance_non_blocking(monkeypatch) -> None:
    original_load = validator.load_object

    def load_with_blocking_core_steps(path: Path):
        value = original_load(path)
        if path.name == "core_step_results.json":
            value = copy.deepcopy(value)
            value["performance_is_a_delivery_gate"] = True
        return value

    monkeypatch.setattr(validator, "load_object", load_with_blocking_core_steps)
    report = validator.validate(ROOT)
    assert "core step results are incomplete" in report["errors"]
