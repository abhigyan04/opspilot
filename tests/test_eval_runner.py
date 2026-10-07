import json

import pytest

from app.agent.schemas import diagnosis_adapter
from evals import runner
from evals.cases import EvaluationCase


def test_runner_passes_incident_and_observations_without_reference(monkeypatch):
    case = EvaluationCase(
        case_id="runner_test",
        incident="Investigate checkout-service.",
        required_tools=frozenset({"search_logs"}),
        reference_root_cause="REFERENCE ANSWER MUST NOT REACH MODEL CALLS",
    )
    investigation = {
        "status": "finished",
        "reason": "Evidence collected.",
        "steps": [{
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
                "reason": "Inspect errors.",
            },
            "result": [],
        }],
    }
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No matching logs were returned.",
        "missing_evidence": ["Application error details"],
    })
    calls = []

    def fake_investigate(incident):
        assert incident == case.incident
        assert case.reference_root_cause not in incident
        calls.append("investigate")
        return investigation

    def fake_generate_diagnosis(incident, steps):
        assert incident == case.incident
        assert steps == investigation["steps"]
        assert case.reference_root_cause not in json.dumps([incident, steps])
        calls.append("diagnosis")
        return diagnosis

    monkeypatch.setattr(runner, "investigate", fake_investigate)
    monkeypatch.setattr(runner, "generate_diagnosis", fake_generate_diagnosis)

    report = runner.run_case(case)

    assert calls == ["investigate", "diagnosis"]
    assert report["metrics"]["required_tool_coverage"] == 1.0
    assert report["diagnosis"]["status"] == "insufficient_evidence"
    assert report["diagnosis_assessment"] == {
        "status": "not_scored",
        "reference_root_cause": case.reference_root_cause,
    }
    assert report["investigation"] == investigation
    assert all(value >= 0 for value in report["timing"].values())


def test_save_report_creates_directory_and_preserves_contents(tmp_path):
    report = {
        "run_id": "test-run",
        "diagnosis_assessment": {"status": "not_scored"},
    }

    destination = runner.save_report(report, tmp_path / "reports")

    assert destination.name == "test-run.json"
    assert json.loads(destination.read_text(encoding="utf-8")) == report


def test_save_report_refuses_to_overwrite(tmp_path):
    original = {"run_id": "same-run", "value": "original"}
    replacement = {"run_id": "same-run", "value": "replacement"}

    destination = runner.save_report(original, tmp_path)

    with pytest.raises(FileExistsError):
        runner.save_report(replacement, tmp_path)

    assert json.loads(destination.read_text(encoding="utf-8")) == original
