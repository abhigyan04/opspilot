import json
import pytest
from types import SimpleNamespace

from app.agent.schemas import diagnosis_adapter
from app.agent.settings import DiagnosisSettings
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

    def fake_investigate(incident, *, data_dir, usage):
        assert incident == case.incident
        assert data_dir == case.scenario_dir
        assert case.reference_root_cause not in incident
        calls.append("investigate")
        return investigation

    def fake_generate_diagnosis(incident, steps, *, model, settings, usage):
        assert incident == case.incident
        assert steps == investigation["steps"]
        assert model == runner.DEFAULT_DIAGNOSIS_MODEL
        assert settings == DiagnosisSettings()
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
    assert report["evaluation_mode"] == "full_pipeline"
    assert report["diagnosis_model"] == runner.DEFAULT_DIAGNOSIS_MODEL
    assert report["diagnosis_settings"] == DiagnosisSettings().model_dump(mode="json")
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

    def fake_investigate(incident, *, data_dir, usage):
        if stage == "investigation":
            raise RuntimeError("Investigation unavailable")
        return investigation

    def fake_diagnosis(incident, steps, *, model, settings, usage):
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


@pytest.mark.parametrize("custom_configuration", [False, True])
def test_batch_saves_failed_attempt_before_continuing(monkeypatch, tmp_path, custom_configuration):
    attempts = []
    
    selected_model = (
        "qwen3:8b"
        if custom_configuration
        else runner.DEFAULT_DIAGNOSIS_MODEL
    )
    selected_settings = (
        DiagnosisSettings(seed=44, think=False)
        if custom_configuration
        else None
    )
    received_configuration = []

    def fake_run_case(case, *, diagnosis_model, diagnosis_settings):
        received_configuration.append(
            (diagnosis_model, diagnosis_settings)
        )
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

    configuration = {}
    if custom_configuration:
        configuration = {
            "diagnosis_model": selected_model,
            "diagnosis_settings": selected_settings,
        }

    batch = runner.run_batch(
        CHECKOUT_REGRESSION,
        2,
        tmp_path,
        **configuration,
    )

    assert received_configuration == [
        (selected_model, selected_settings),
        (selected_model, selected_settings),
    ]

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


def test_cli_defaults_to_checkout_case():
    args = runner.parse_arguments([])

    assert args.case == "checkout_regression"
    assert args.runs == 1


def test_cli_selects_payment_provider_case():
    args = runner.parse_arguments([
        "--case", "payment_provider_outage",
        "--runs", "2",
    ])

    assert args.case == "payment_provider_outage"
    assert args.runs == 2
    assert runner.CASES[args.case].scenario_dir.name == "payment_provider_outage"


@pytest.mark.parametrize("arguments", [
    ["--case", "unknown_case"],
    ["--runs", "0"],
])
def test_cli_rejects_invalid_arguments(arguments):
    with pytest.raises(SystemExit) as error:
        runner.parse_arguments(arguments)

    assert error.value.code == 2


def test_cli_selects_sparse_evidence_case():
    args = runner.parse_arguments(["--case", "sparse_evidence"])

    assert args.case == "sparse_evidence"
    assert runner.CASES[args.case].scenario_dir.name == "sparse_evidence"


@pytest.mark.parametrize("diagnosis_fails", [False, True])
def test_run_case_forwards_and_records_diagnosis_configuration(monkeypatch, diagnosis_fails):
    investigation = {
        "status": "finished",
        "reason": "Evidence collected.",
        "steps": [],
    }
    settings = DiagnosisSettings(seed=43, think=False)
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No operational evidence was collected.",
        "missing_evidence": ["Operational tool results"],
    })
    received = []

    def fake_investigate(incident, *, data_dir, usage):
        return investigation

    def fake_generate(incident, steps, *, model, settings, usage):
        received.append((incident, steps, model, settings))
        if diagnosis_fails:
            raise RuntimeError("Diagnosis unavailable")
        return diagnosis

    monkeypatch.setattr(runner, "investigate", fake_investigate)
    monkeypatch.setattr(runner, "generate_diagnosis", fake_generate)

    report = runner.run_case(
        CHECKOUT_REGRESSION,
        diagnosis_model="qwen3:8b",
        diagnosis_settings=settings,
    )

    assert received == [
        (CHECKOUT_REGRESSION.incident, [], "qwen3:8b", settings)
    ]
    assert report["evaluation_mode"] == "full_pipeline"
    assert report["diagnosis_model"] == "qwen3:8b"
    assert report["diagnosis_settings"] == settings.model_dump(mode="json")
    assert report["status"] == (
        "failed" if diagnosis_fails else "completed"
    )

    if diagnosis_fails:
        assert report["error"]["stage"] == "diagnosis"
        assert report["diagnosis"] is None
    else:
        assert report["error"] is None
        assert report["diagnosis"] == diagnosis.model_dump(mode="json")


def test_cli_defaults_to_explicit_diagnosis_settings():
    args = runner.parse_arguments([])

    assert args.model == runner.DEFAULT_DIAGNOSIS_MODEL
    assert args.diagnosis_settings == DiagnosisSettings()


@pytest.mark.parametrize("failed", [0, 1])
def test_cli_forwards_configuration_and_returns_batch_status(monkeypatch, capsys, failed):
    calls = []

    def fake_run_batch(
        case,
        runs,
        output_directory,
        *,
        diagnosis_model,
        diagnosis_settings,
    ):
        calls.append({
            "case": case.case_id,
            "runs": runs,
            "model": diagnosis_model,
            "settings": diagnosis_settings.model_dump(mode="json"),
        })
        return {"summary": {"failed": failed}}

    monkeypatch.setattr(runner, "run_batch", fake_run_batch)

    exit_code = runner.main([
        "--case", "payment_provider_outage",
        "--runs", "2",
        "--model", "qwen3:8b",
        "--num-ctx", "4096",
        "--temperature", "0.2",
        "--top-p", "0.9",
        "--top-k", "30",
        "--seed", "44",
        "--no-think",
    ])

    assert calls == [{
        "case": "payment_provider_outage",
        "runs": 2,
        "model": "qwen3:8b",
        "settings": {
            "num_ctx": 4096,
            "temperature": 0.2,
            "top_p": 0.9,
            "top_k": 30,
            "seed": 44,
            "think": False,
        },
    }]
    assert exit_code == (1 if failed else 0)
    assert json.loads(capsys.readouterr().out) == {
        "summary": {"failed": failed}
    }


@pytest.mark.parametrize("arguments", [
    ["--model", "   "],
    ["--num-ctx", "0"],
    ["--temperature", "-1"],
    ["--temperature", "nan"],
    ["--top-p", "1.1"],
    ["--top-k", "0"],
    ["--seed", "-1"],
])
def test_invalid_diagnosis_configuration_never_starts_batch(monkeypatch, arguments):
    def unexpected_batch(*args, **kwargs):
        pytest.fail("Invalid configuration must not start a batch.")

    monkeypatch.setattr(runner, "run_batch", unexpected_batch)

    with pytest.raises(SystemExit) as error:
        runner.main(arguments)

    assert error.value.code == 2


@pytest.mark.parametrize("failure_stage", [None, "investigation", "diagnosis"])
def test_runner_persists_usage_without_leaking_between_runs(monkeypatch, tmp_path, failure_stage):
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No matching error details were returned.",
        "missing_evidence": ["Error details"],
    })

    def fake_investigate(incident, *, data_dir, usage):
        usage.record(
            stage="investigation",
            model="qwen3:4b",
            response=SimpleNamespace(
                prompt_eval_count=100,
                eval_count=20,
            ),
        )
        if failure_stage == "investigation":
            raise ValueError("Investigation response rejected")

        return {
            "status": "finished",
            "reason": "No matching records.",
            "steps": [],
        }

    def fake_diagnosis(incident, steps, *, model, settings, usage):
        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(
                prompt_eval_count=200,
                eval_count=40,
            ),
        )
        if failure_stage == "diagnosis":
            raise ValueError("Diagnosis response rejected")
        return diagnosis

    monkeypatch.setattr(runner, "investigate", fake_investigate)
    monkeypatch.setattr(runner, "generate_diagnosis", fake_diagnosis)

    # Each run must start with its own empty collector.
    for _ in range(2):
        report = runner.run_case(
            CHECKOUT_REGRESSION,
            diagnosis_model="qwen3:8b",
        )

        investigation_only = failure_stage == "investigation"
        expected_stages = (
            ["investigation"]
            if investigation_only
            else ["investigation", "diagnosis"]
        )
        usage = report["usage"]

        assert [call["stage"] for call in usage["calls"]] == expected_stages
        assert usage["totals"]["attempts"] == len(expected_stages)
        assert usage["totals"]["input_tokens"] == (
            100 if investigation_only else 300
        )
        assert usage["totals"]["output_tokens"] == (
            20 if investigation_only else 60
        )

        if failure_stage is None:
            assert report["status"] == "completed"
        else:
            assert report["status"] == "failed"
            assert report["error"]["stage"] == failure_stage

        destination = runner.save_report(report, tmp_path)
        saved = json.loads(destination.read_text(encoding="utf-8"))
        assert saved["usage"] == usage
