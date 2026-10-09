import hashlib
import json

import pytest

from evals.replay import load_replay_source
from app.agent.schemas import diagnosis_adapter
from evals import replay
from evals.summary import summarize_reports


def sample_report():
    return {
        "report_version": 2,
        "run_id": "original-run",
        "case_id": "checkout_regression",
        "incident": "Investigate checkout-service.",
        "status": "failed",
        "error": {"stage": "diagnosis"},
        "investigation": {
            "status": "finished",
            "reason": "Evidence collection finished.",
            "steps": [],
        },
        "diagnosis": None,
    }


def write_report(tmp_path, report):
    path = tmp_path / "original-run.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_loader_accepts_diagnosis_failure_and_preserves_source(tmp_path):
    report = sample_report()
    path = write_report(tmp_path, report)
    original_bytes = path.read_bytes()

    source = load_replay_source(path)

    assert source["report"] == report
    assert source["source_report"] == path.name
    assert source["source_sha256"] == hashlib.sha256(
        original_bytes
    ).hexdigest()
    assert path.read_bytes() == original_bytes


def test_loader_accepts_step_limit_investigation(tmp_path):
    report = sample_report()
    report["investigation"]["status"] = "step_limit"
    path = write_report(tmp_path, report)

    source = load_replay_source(path)

    assert source["report"]["investigation"]["status"] == "step_limit"


@pytest.mark.parametrize("field, value, message", [
    ("report_version", 1, "version 2"),
    ("investigation", None, "saved investigation"),
    (
        "investigation",
        {"status": "running", "steps": []},
        "completed investigation",
    ),
    (
        "investigation",
        {"status": "finished", "steps": None},
        "steps list",
    ),
    ("incident", "   ", "nonblank incident"),
])
def test_loader_rejects_unusable_sources(tmp_path, field, value, message):
    report = sample_report()
    report[field] = value
    path = write_report(tmp_path, report)

    with pytest.raises(ValueError, match=message):
        load_replay_source(path)


def test_replay_uses_saved_evidence_without_previous_answers(
    monkeypatch, tmp_path
):
    original = sample_report()
    original["diagnosis"] = {"reason": "OLD DIAGNOSIS"}
    original["diagnosis_assessment"] = {
        "status": "not_scored",
        "reference_root_cause": "REFERENCE ANSWER",
    }
    original["investigation"]["steps"] = [{
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
    }]
    path = write_report(tmp_path, original)
    original_bytes = path.read_bytes()
    calls = []

    def fake_generate(incident, steps, *, model):
        assert model == "qwen3:4b"
        assert incident == original["incident"]
        assert steps == original["investigation"]["steps"]
        assert "OLD DIAGNOSIS" not in json.dumps([incident, steps])
        assert "REFERENCE ANSWER" not in json.dumps([incident, steps])
        calls.append(True)

        # A callee must not mutate the evidence saved in the replay.
        steps.clear()
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No matching error logs.",
            "missing_evidence": ["Application error details"],
        })

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    result = replay.replay_diagnosis(path)

    assert calls == [True]
    assert result["run_id"] != original["run_id"]
    assert result["evaluation_mode"] == "diagnosis_replay"
    assert result["diagnosis_model"] == "qwen3:4b"
    assert result["status"] == "completed"
    assert result["error"] is None
    assert result["investigation"] == original["investigation"]
    assert result["diagnosis"]["status"] == "insufficient_evidence"
    assert result["diagnosis_assessment"] == original["diagnosis_assessment"]
    assert result["source"]["run_id"] == original["run_id"]
    assert result["source"]["sha256"] == hashlib.sha256(
        original_bytes
    ).hexdigest()
    assert result["metrics"] is None
    assert result["timing"]["investigation_seconds"] is None
    assert result["timing"]["scoring_seconds"] is None
    assert result["timing"]["diagnosis_seconds"] >= 0
    assert path.read_bytes() == original_bytes


def test_replay_records_diagnosis_failure(monkeypatch, tmp_path):
    original = sample_report()
    path = write_report(tmp_path, original)

    def fail_diagnosis(incident, steps, *, model):
        assert model == "qwen3:4b"
        raise ValueError("Invalid citation")

    monkeypatch.setattr(replay, "generate_diagnosis", fail_diagnosis)

    result = replay.replay_diagnosis(path)

    assert result["diagnosis_model"] == "qwen3:4b"
    assert result["status"] == "failed"
    assert result["diagnosis"] is None
    assert result["investigation"] == original["investigation"]
    assert result["error"] == {
        "stage": "diagnosis",
        "type": "ValueError",
        "message": "Invalid citation",
    }
    assert result["timing"]["diagnosis_seconds"] >= 0


def test_invalid_source_does_not_start_diagnosis(monkeypatch, tmp_path):
    original = sample_report()
    original["investigation"] = None
    path = write_report(tmp_path, original)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Invalid source must not start diagnosis.")

    monkeypatch.setattr(replay, "generate_diagnosis", unexpected_call)

    with pytest.raises(ValueError, match="saved investigation"):
        replay.replay_diagnosis(path)


def test_pipeline_summary_rejects_replay_reports():
    with pytest.raises(ValueError, match="diagnosis replays"):
        summarize_reports([{
            "report_version": 2,
            "evaluation_mode": "diagnosis_replay",
        }])


@pytest.mark.parametrize("status, expected_exit", [
    ("completed", 0),
    ("failed", 1),
])
def test_cli_saves_result_and_returns_matching_exit_code(
    monkeypatch, tmp_path, capsys, status, expected_exit
):
    source_path = tmp_path / "source.json"
    output_dir = tmp_path / "replays"
    report = {
        "run_id": "new-replay",
        "evaluation_mode": "diagnosis_replay",
        "diagnosis_model": "qwen3:4b",
        "status": status,
        "source": {"run_id": "original-run"},
        "timing": {"diagnosis_seconds": 1.0},
        "error": None if status == "completed" else {
            "stage": "diagnosis",
            "type": "ValueError",
            "message": "Invalid citation",
        },
    }

    def fake_replay(path, *, model):
        assert path == source_path
        assert model == "qwen3:4b"
        return report

    monkeypatch.setattr(replay, "replay_diagnosis", fake_replay)

    exit_code = replay.main([
        str(source_path),
        "--output-dir", str(output_dir),
    ])

    destination = output_dir / "new-replay.json"
    assert exit_code == expected_exit
    assert json.loads(destination.read_text(encoding="utf-8")) == report

    printed = json.loads(capsys.readouterr().out)
    assert printed["diagnosis_model"] == "qwen3:4b"
    assert printed["report_path"] == str(destination)
    assert printed["status"] == status


def test_cli_reports_invalid_source_without_saving(
    monkeypatch, tmp_path, capsys
):
    def invalid_source(path, *, model):
        raise ValueError("Replay requires a saved investigation.")

    monkeypatch.setattr(replay, "replay_diagnosis", invalid_source)
    output_dir = tmp_path / "replays"

    exit_code = replay.main([
        str(tmp_path / "source.json"),
        "--output-dir", str(output_dir),
    ])

    assert exit_code == 1
    assert not output_dir.exists()
    assert "saved investigation" in capsys.readouterr().out


def test_cli_preserves_existing_report_on_save_collision(
    monkeypatch, tmp_path, capsys
):
    output_dir = tmp_path / "replays"
    output_dir.mkdir()
    destination = output_dir / "same-id.json"
    destination.write_text('{"original": true}', encoding="utf-8")
    original_bytes = destination.read_bytes()

    monkeypatch.setattr(
        replay,
        "replay_diagnosis",
        lambda path, *, model: {"run_id": "same-id"},
    )

    exit_code = replay.main([
        str(tmp_path / "source.json"),
        "--output-dir", str(output_dir),
    ])

    assert exit_code == 1
    assert destination.read_bytes() == original_bytes
    assert "Replay failed:" in capsys.readouterr().out


def test_cli_forwards_and_records_selected_model(
    monkeypatch, tmp_path, capsys
):
    original = sample_report()
    original["investigation"]["steps"] = [{
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
    }]
    source_path = write_report(tmp_path, original)
    output_dir = tmp_path / "replays"
    calls = []

    def fake_generate(incident, steps, *, model):
        assert incident == original["incident"]
        assert steps == original["investigation"]["steps"]
        calls.append(model)
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No matching error logs.",
            "missing_evidence": ["Application error details"],
        })

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    exit_code = replay.main([
        str(source_path),
        "--model", "qwen3:8b",
        "--output-dir", str(output_dir),
    ])

    printed = json.loads(capsys.readouterr().out)
    saved_path = output_dir / f"{printed['run_id']}.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert calls == ["qwen3:8b"]
    assert printed["diagnosis_model"] == "qwen3:8b"
    assert saved["diagnosis_model"] == "qwen3:8b"
    assert saved["investigation"] == original["investigation"]
