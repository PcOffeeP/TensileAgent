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
