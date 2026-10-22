import hashlib
import json
from pathlib import Path

import pytest

from app.agent.schemas import RollbackProposal
from evals import remediation_runner


def write_source(tmp_path, **overrides):
    report = {
        "report_version": 2,
        "evaluation_mode": "diagnosis_replay",
        "run_id": "saved-run",
        "case_id": "payment_provider_outage",
        "status": "completed",
        "incident": "Investigate checkout-service.",
        "investigation": {
            "status": "finished",
            "steps": [],
        },
        "diagnosis": {
            "status": "insufficient_evidence",
            "reason": "No operational evidence was collected.",
            "missing_evidence": ["Operational observations"],
        },
        "diagnosis_assessment": {
            "reference_root_cause": "Evaluation-only reference.",
        },
        **overrides,
    }
    path = tmp_path / "source.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_saved_evaluation_preserves_source_and_records_provenance(tmp_path):
    path = write_source(tmp_path)
    original = path.read_bytes()

    result = remediation_runner.evaluate_saved_remediation(
        path, service="checkout-service"
    )

    assert path.read_bytes() == original
    assert result["source_report"] == path.name
    assert result["source_run_id"] == "saved-run"
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["diagnosis_status"] == "insufficient_evidence"
    assert result["proposal"] is None
    assert result["matches_expectation"] is True


@pytest.mark.parametrize("overrides", [
    {"status": "failed"},
    {"diagnosis": None},
    {"case_id": "unknown-case"},
    {"evaluation_mode": "remediation_proposal_comparison"},
])
def test_invalid_source_does_not_reach_proposal_builder(
    tmp_path, monkeypatch, overrides
):
    path = write_source(tmp_path, **overrides)

    def unexpected_builder(*args, **kwargs):
        pytest.fail("Invalid source reached proposal generation.")

    monkeypatch.setattr(
        remediation_runner, "build_rollback_proposal", unexpected_builder
    )

    with pytest.raises(ValueError):
        remediation_runner.evaluate_saved_remediation(
            path, service="checkout-service"
        )


def test_builder_receives_only_operational_inputs(tmp_path, monkeypatch):
    path = write_source(tmp_path)
    calls = []

    def fake_builder(diagnosis, service, steps):
        calls.append((diagnosis.model_dump(), service, steps))
        return RollbackProposal(
            action="rollback_service",
            service=service,
            current_version="1.7.4",
            target_version="1.7.3",
            reason="Synthetic inappropriate candidate for evaluation.",
            evidence_ids=["evidence-001"],
        )

    monkeypatch.setattr(
        remediation_runner, "build_rollback_proposal", fake_builder
    )

    result = remediation_runner.evaluate_saved_remediation(
        path, service="checkout-service"
    )

    original = json.loads(path.read_text(encoding="utf-8"))
    expected_diagnosis = {
        **original["diagnosis"],
        "reference_notes": original["diagnosis"].get("reference_notes", []),
    }
    assert calls == [(expected_diagnosis, "checkout-service", [])]
    assert result["matches_expectation"] is False
    assert result["expected_proposal"] is None
    assert result["actual_proposal"]["action"] == "rollback_service"


def test_runner_rejects_duplicate_sources(tmp_path):
    path = write_source(tmp_path)

    with pytest.raises(ValueError, match="Duplicate source run ID"):
        remediation_runner.evaluate_remediation_reports(
            [path, path], service="checkout-service"
        )


def test_runner_rejects_empty_input():
    with pytest.raises(ValueError, match="At least one"):
        remediation_runner.evaluate_remediation_reports(
            [], service="checkout-service"
        )


@pytest.mark.parametrize("directory_input", [False, True])
def test_cli_saves_evaluation_report(tmp_path, capsys, directory_input):
    source_directory = tmp_path / "inputs"
    source_directory.mkdir()
    path = write_source(source_directory)
    original = path.read_bytes()
    output_directory = tmp_path / "outputs"

    exit_code = remediation_runner.main([
        str(source_directory if directory_input else path),
        "--service", "checkout-service",
        "--output-dir", str(output_directory),
    ])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    saved = json.loads(
        Path(printed["report_path"]).read_text(encoding="utf-8")
    )

    assert saved["evaluation_mode"] == "remediation_proposal_evaluation"
    assert saved["total_attempts"] == 1
    assert saved["matching_proposals"] == 1
    assert saved["by_case"] == {
        "payment_provider_outage": {"attempts": 1, "matches": 1}
    }
    assert saved["results"][0]["source_sha256"] == (
        hashlib.sha256(original).hexdigest()
    )
    assert set(saved["code_sha256"]) == {
        "proposal_policy", "evaluator", "runner"
    }
    assert path.read_bytes() == original


def test_cli_does_not_save_partial_evaluation(tmp_path, capsys):
    source_directory = tmp_path / "inputs"
    source_directory.mkdir()
    first = write_source(source_directory)
    first.rename(source_directory / "a-valid.json")
    write_source(source_directory, run_id="failed-run", status="failed")
    output_directory = tmp_path / "outputs"

    exit_code = remediation_runner.main([
        str(source_directory),
        "--service", "checkout-service",
        "--output-dir", str(output_directory),
    ])

    assert exit_code == 1
    assert "completed report" in capsys.readouterr().out
    assert not output_directory.exists()


def test_cli_rejects_output_inside_comparison(tmp_path, capsys):
    write_source(tmp_path)

    exit_code = remediation_runner.main([
        str(tmp_path),
        "--service", "checkout-service",
        "--output-dir", str(tmp_path / "generated"),
    ])

    assert exit_code == 1
    assert "outside the comparison directory" in capsys.readouterr().out
    assert not (tmp_path / "generated").exists()
