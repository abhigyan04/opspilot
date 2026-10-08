import json

import pytest

from app.agent.schemas import diagnosis_adapter
from evals import runner
from evals.cases import EvaluationCase, CHECKOUT_REGRESSION


def test_runner_passes_incident_and_observations_without_reference(monkeypatch, tmp_path):
    case = EvaluationCase(
        case_id="runner_test",
        incident="Investigate checkout-service.",
        required_tools=frozenset({"search_logs"}),
        reference_root_cause="REFERENCE ANSWER MUST NOT REACH MODEL CALLS",
        scenario_dir=tmp_path / "selected-scenario"
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

    def fake_investigate(incident, *, data_dir):
        assert incident == case.incident
        assert data_dir == case.scenario_dir
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
    assert report["status"] == "completed"
    assert report["error"] is None
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


@pytest.mark.parametrize("stage", ["investigation", "diagnosis"])
def test_failed_run_preserves_available_results(monkeypatch, tmp_path, stage):
    investigation = {
        "status": "finished",
        "reason": "Stopped.",
        "steps": [],
    }

    def fake_investigate(incident, *, data_dir):
        if stage == "investigation":
            raise RuntimeError("Investigation unavailable")
        return investigation

    def fake_diagnosis(incident, steps):
        if stage == "investigation":
            pytest.fail("Diagnosis must not run after investigation fails.")
        raise ValueError("Invalid diagnosis")

    monkeypatch.setattr(runner, "investigate", fake_investigate)
    monkeypatch.setattr(runner, "generate_diagnosis", fake_diagnosis)

    report = runner.run_case(CHECKOUT_REGRESSION)

    assert report["status"] == "failed"
    assert report["error"]["stage"] == stage
    assert report["diagnosis"] is None
    assert report["timing"][f"{stage}_seconds"] >= 0

    if stage == "investigation":
        assert report["investigation"] is None
        assert report["metrics"] is None
        assert report["timing"]["diagnosis_seconds"] is None
    else:
        assert report["investigation"] == investigation
        assert report["metrics"]["required_tool_coverage"] == 0.0

    destination = runner.save_report(report, tmp_path)
    assert json.loads(destination.read_text(encoding="utf-8")) == report


def test_batch_saves_failed_attempt_before_continuing(monkeypatch, tmp_path):
    attempts = []

    def fake_run_case(case):
        index = len(attempts)

        if index == 1:
            saved = list(tmp_path.glob("*/attempt-0.json"))
            assert len(saved) == 1
            first = json.loads(saved[0].read_text(encoding="utf-8"))
            assert first["status"] == "failed"

        failed = index == 0
        report = {
            "report_version": 2,
            "run_id": f"attempt-{index}",
            "case_id": case.case_id,
            "status": "failed" if failed else "completed",
            "metrics": (
                None if failed
                else {"required_tool_coverage": 1.0}
            ),
            "timing": {"total_seconds": 1.0},
            "error": (
                {"stage": "investigation", "type": "RuntimeError",
                 "message": "Model unavailable"}
                if failed else None
            ),
        }
        attempts.append(report)
        return report

    monkeypatch.setattr(runner, "run_case", fake_run_case)

    batch = runner.run_batch(CHECKOUT_REGRESSION, 2, tmp_path)

    assert len(attempts) == 2
    assert batch["summary"]["attempts"] == 2
    assert batch["summary"]["failed"] == 1
    assert batch["summary"]["completed"] == 1
    assert batch["report_files"] == [
        "attempt-0.json",
        "attempt-1.json",
    ]

    saved_summary = json.loads(
        (tmp_path / batch["batch_id"] / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved_summary["summary"] == batch["summary"]


@pytest.mark.parametrize("runs", [0, -1])
def test_batch_rejects_invalid_count_before_running(monkeypatch, tmp_path, runs):
    def unexpected_run(case):
        pytest.fail("Invalid batch size must not start a model run.")

    monkeypatch.setattr(runner, "run_case", unexpected_run)

    with pytest.raises(ValueError, match="at least 1"):
        runner.run_batch(CHECKOUT_REGRESSION, runs, tmp_path)
