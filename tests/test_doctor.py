from unittest.mock import MagicMock

from agent.contract import visual_contract_hash
from agent.doctor import run_doctor


def test_doctor_authenticates_visual_contract_preflight(monkeypatch, tmp_path):
    config = {
        "agent": {
            "local": {
                "model": "decision-model",
                "base_url": "http://localhost:11434/v1",
            }
        },
        "backend": {
            "api_url": "http://100.70.83.68:8001/v1",
            "model": "tensile-vlm",
        },
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.doctor.load_config", lambda _path: config)
    monkeypatch.setattr("agent.doctor.get_local_model_digest", lambda *_args: "digest")
    monkeypatch.setattr("agent.doctor.get_inference_api_key", lambda: "visual-secret")
    monkeypatch.setattr("agent.doctor.shutil.which", lambda binary: f"/usr/bin/{binary}")

    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "contract_version": "tensile-vlm/v2",
        "contract_hash": visual_contract_hash(),
    }
    get = MagicMock(return_value=response)
    monkeypatch.setattr("agent.doctor.requests.get", get)

    result = run_doctor()

    assert result["ok"] is True
    assert result["checks"]["visual_service"]["auth_configured"] is True
    get.assert_called_once_with(
        "http://100.70.83.68:8001/v1/tensile/contract",
        headers={"Authorization": "Bearer visual-secret"},
        timeout=3,
    )
