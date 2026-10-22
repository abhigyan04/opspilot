import hashlib
import json
import pytest
from types import SimpleNamespace
from contextlib import contextmanager

from evals.replay import load_replay_source
from app.agent.schemas import diagnosis_adapter
from evals import replay
from evals.summary import summarize_reports
from app.agent.settings import DiagnosisSettings
from app.agent.usage import UsageCollector
from app.retrieval.chunks import KnowledgeChunk
from app.retrieval.context import build_reference_context
from app.retrieval.search import SearchHit


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

    def fake_generate(incident, steps, *, model, settings, usage):
        assert model == "qwen3:4b"
        assert settings == DiagnosisSettings()
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

    def fail_diagnosis(incident, steps, *, model, settings, usage):
        assert model == "qwen3:4b"
        assert settings == DiagnosisSettings()
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
def test_cli_saves_result_and_returns_matching_exit_code(monkeypatch, tmp_path, capsys, status, expected_exit):
    source_path = tmp_path / "source.json"
    output_dir = tmp_path / "replays"
    report = {
        "run_id": "new-replay",
        "evaluation_mode": "diagnosis_replay",
        "diagnosis_model": "qwen3:4b",
        "diagnosis_settings": DiagnosisSettings().model_dump(mode="json"),
        "status": status,
        "source": {"run_id": "original-run"},
        "timing": {"diagnosis_seconds": 1.0},
        "error": None if status == "completed" else {
            "stage": "diagnosis",
            "type": "ValueError",
            "message": "Invalid citation",
        },
        "usage": UsageCollector().snapshot()
    }

    def fake_replay(path, *, model, settings):
        assert path == source_path
        assert model == "qwen3:4b"
        assert settings == DiagnosisSettings()
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
    assert printed["diagnosis_settings"] == report["diagnosis_settings"]
    assert printed["usage"] == report["usage"]


def test_cli_reports_invalid_source_without_saving(
    monkeypatch, tmp_path, capsys
):
    def invalid_source(path, *, model, settings):
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
        lambda path, *, model, settings: {"run_id": "same-id"},
    )

    exit_code = replay.main([
        str(tmp_path / "source.json"),
        "--output-dir", str(output_dir),
    ])

    assert exit_code == 1
    assert destination.read_bytes() == original_bytes
    assert "Replay failed:" in capsys.readouterr().out


@pytest.mark.parametrize("settings_args, expected_settings", [
    (
        [],
        DiagnosisSettings(),
    ),
    (
        [
            "--num-ctx", "2048",
            "--temperature", "0.7",
            "--top-p", "0.8",
            "--top-k", "30",
            "--seed", "7",
            "--no-think",
        ],
        DiagnosisSettings(
            num_ctx=2048,
            temperature=0.7,
            top_p=0.8,
            top_k=30,
            seed=7,
            think=False,
        ),
    ),
])
def test_cli_forwards_and_records_selected_model(
    monkeypatch, tmp_path, capsys, settings_args, expected_settings
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

    def fake_generate(incident, steps, *, model, settings, usage):
        assert incident == original["incident"]
        assert settings == expected_settings
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
        *settings_args
    ])

    printed = json.loads(capsys.readouterr().out)
    saved_path = output_dir / f"{printed['run_id']}.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert calls == ["qwen3:8b"]
    assert printed["diagnosis_model"] == "qwen3:8b"
    assert saved["diagnosis_model"] == "qwen3:8b"
    assert saved["investigation"] == original["investigation"]
    assert saved["diagnosis_settings"] == (expected_settings.model_dump(mode="json"))
    assert printed["diagnosis_settings"] == saved["diagnosis_settings"]


@pytest.mark.parametrize("fail", [False, True])
def test_replay_records_the_settings_passed_to_diagnosis(
    monkeypatch, tmp_path, fail
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
    path = write_report(tmp_path, original)

    requested = DiagnosisSettings(
        num_ctx=2048,
        temperature=0.7,
        top_p=0.8,
        top_k=30,
        seed=7,
        think=False,
    )
    received = []

    def fake_generate(incident, steps, *, model, settings, usage):
        received.append(settings)
        if fail:
            raise ValueError("Invalid diagnosis")

        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No matching error logs.",
            "missing_evidence": ["Application error details"],
        })

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    result = replay.replay_diagnosis(
        path,
        model="qwen3:8b",
        settings=requested,
    )

    assert received == [requested]
    assert result["diagnosis_settings"] == {
        "num_ctx": 2048,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 30,
        "seed": 7,
        "think": False,
    }
    assert result["status"] == ("failed" if fail else "completed")
    assert result["investigation"] == original["investigation"]


@pytest.mark.parametrize("arguments", [
    ["--num-ctx", "0"],
    ["--temperature", "nan"],
    ["--top-p", "1.1"],
    ["--top-k", "0"],
    ["--seed", "-1"],
    ["retrieval-top-k", "0"]
])
def test_invalid_cli_settings_stop_before_replay(monkeypatch, tmp_path, capsys, arguments):
    def unexpected_replay(*args, **kwargs):
        pytest.fail("Invalid settings must not start replay.")

    monkeypatch.setattr(replay, "replay_diagnosis", unexpected_replay)
    output_dir = tmp_path / "replays"

    with pytest.raises(SystemExit) as error:
        replay.main([
            str(tmp_path / "source.json"),
            "--output-dir", str(output_dir),
            *arguments,
        ])

    assert error.value.code == 2
    assert not output_dir.exists()
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("diagnosis_fails", [False, True])
def test_replay_records_only_new_usage_and_preserves_source(monkeypatch, tmp_path, diagnosis_fails):
    source = sample_report()

    historical_usage = UsageCollector()
    historical_usage.record(
        stage="investigation",
        model="qwen3:4b",
        response=SimpleNamespace(
            prompt_eval_count=9000,
            eval_count=1000,
        ),
    )
    source["usage"] = historical_usage.snapshot()

    path = write_report(tmp_path, source)
    original_bytes = path.read_bytes()

    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No operational evidence was collected.",
        "missing_evidence": ["Operational tool results"],
    })

    def fake_generate(incident, steps, *, model, settings, usage):
        assert usage.snapshot()["totals"]["attempts"] == 0
        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(
                prompt_eval_count=120,
                eval_count=30,
            ),
        )
        if diagnosis_fails:
            raise ValueError("Diagnosis response rejected")
        return diagnosis

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    # Each replay must start fresh, even when reusing the same source.
    for _ in range(2):
        result = replay.replay_diagnosis(path, model="qwen3:8b")

        assert result["usage"]["calls"] == [{
            "stage": "diagnosis",
            "model": "qwen3:8b",
            "input_tokens": 120,
            "output_tokens": 30,
        }]
        assert result["usage"]["totals"]["attempts"] == 1
        assert result["usage"]["totals"]["input_tokens"] == 120
        assert result["usage"]["totals"]["output_tokens"] == 30
        assert result["status"] == (
            "failed" if diagnosis_fails else "completed"
        )

        destination = replay.save_report(result, tmp_path / "replays")
        saved = json.loads(destination.read_text(encoding="utf-8"))
        assert saved["usage"] == result["usage"]

    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("diagnosis_fails", [False, True])
def test_replay_records_references_even_when_diagnosis_fails(monkeypatch, tmp_path, diagnosis_fails):
    original = sample_report()
    original["investigation"]["steps"] = [{
        "evidence_id": "evidence-001",
        "decision": {
            "tool": "search_logs",
            "arguments": {"service": "checkout-service"},
        },
        "result": [{"message": "Request timed out."}],
    }]
    path = write_report(tmp_path, original)
    original_bytes = path.read_bytes()

    hit = SearchHit(
        chunk=KnowledgeChunk(
            chunk_id="dependency-guide:abc:1",
            document_id="dependency-guide",
            document_type="runbook",
            title="Dependency guide",
            section="Investigation",
            source_path="runbooks/dependency-guide.md",
            synthetic=True,
            source_sha256="a" * 64,
            content="Compare dependency failures with deployment timing.",
        ),
        score=0.8,
    )
    hits = [hit]
    expected_context = build_reference_context(hits)
    calls = []

    def fake_generate(
        incident, steps, *, model, settings, usage, reference_hits
    ):
        assert incident == original["incident"]
        assert steps == original["investigation"]["steps"]
        assert build_reference_context(reference_hits) == expected_context
        calls.append(True)

        # Mutation by the callee must not alter the caller or saved context.
        reference_hits.clear()

        if diagnosis_fails:
            raise RuntimeError("Model unavailable")

        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "The timeout's cause is not established.",
            "missing_evidence": ["Dependency error details"],
        })

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    result = replay.replay_diagnosis(path, reference_hits=hits)

    assert calls == [True]
    assert hits == [hit]
    assert result["reference_context"] == expected_context
    assert result["investigation"] == original["investigation"]
    assert path.read_bytes() == original_bytes

    if diagnosis_fails:
        assert result["status"] == "failed"
        assert result["error"]["stage"] == "diagnosis"
        assert result["diagnosis"] is None
    else:
        assert result["status"] == "completed"
        assert result["error"] is None


def test_replay_without_references_records_empty_context(monkeypatch, tmp_path):
    path = write_report(tmp_path, sample_report())

    def fake_generate(incident, steps, *, model, settings, usage):
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No operational evidence was collected.",
            "missing_evidence": ["Operational tool results"],
        })

    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    result = replay.replay_diagnosis(path)

    assert result["status"] == "completed"
    assert result["reference_context"] == []


@pytest.mark.parametrize("failure_stage", [None, "retrieval", "diagnosis"])
@pytest.mark.parametrize("with_errors", [False, True])
def test_postgres_replay_records_provenance_and_failure_stage(monkeypatch, tmp_path, failure_stage, with_errors):
    original = sample_report()
    
    error_message = "Payment authorization failed: PayBridge returned HTTP 503."
    
    if with_errors:
        original["investigation"]["steps"] = [{
            "evidence_id": "evidence_001",
            "decision": {
                "tool": "search_logs",
                "arguments": {"level": "ERROR"},
                "reason": "UNSUPPORTED MODEL REASONING"
            },
            "result": [{
                "level": "ERROR",
                "message": error_message
            }]
        }]
    
    expected_query = error_message if with_errors else original["incident"]
    
    original["diagnosis"] = {"reason": "OLD ANSWER"}
    original["diagnosis_assessment"] = {
        "reference_root_cause": "EXPECTED ANSWER"
    }
    path = write_report(tmp_path, original)
    connection = object()
    calls = []

    hit = SearchHit(
        chunk=KnowledgeChunk(
            chunk_id="dependency-guide:abc:1",
            document_id="dependency-guide",
            document_type="runbook",
            title="Dependency guide",
            section="Investigation",
            source_path="runbooks/dependency-guide.md",
            synthetic=True,
            source_sha256="a" * 64,
            content="Compare failure and deployment timing.",
        ),
        score=0.8,
    )
    identity = {
        "model": "embeddinggemma:300m",
        "digest": "b" * 64,
        "dimensions": 768,
        "format_version": 1,
    }

    def fake_retrieve(query, supplied_connection, *, top_k):
        assert query == expected_query
        assert supplied_connection is connection
        assert top_k == 2
        calls.append("retrieval")

        if failure_stage == "retrieval":
            raise RuntimeError("Database unavailable")

        return SimpleNamespace(
            index_id="c" * 64,
            embedding_identity=identity,
            hits=[hit],
        )

    def fake_generate(
        incident, steps, *, model, settings, usage, reference_hits
    ):
        calls.append("diagnosis")
        assert incident == original["incident"]
        assert steps == original["investigation"]["steps"]
        assert reference_hits == [hit]

        if failure_stage == "diagnosis":
            raise RuntimeError("Model unavailable")

        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No operational evidence was collected.",
            "missing_evidence": ["Operational tool results"],
        })

    monkeypatch.setattr(replay, "retrieve_postgres", fake_retrieve)
    monkeypatch.setattr(replay, "generate_diagnosis", fake_generate)

    result = replay.replay_diagnosis(
        path,
        retrieval_connection=connection,
        retrieval_top_k=2,
    )

    assert result["retrieval"]["query"] == expected_query
    assert result["retrieval"]["query_version"] == 2
    assert result["retrieval"]["query_strategy"] == (
        "errors_only_with_incident_fallback"
    )
    assert result["retrieval"]["backend"] == "postgres"
    assert result["retrieval"]["top_k"] == 2
    assert result["timing"]["retrieval_seconds"] >= 0

    if failure_stage == "retrieval":
        assert calls == ["retrieval"]
        assert result["retrieval"]["index_id"] is None
        assert result["reference_context"] == []
        assert result["timing"]["diagnosis_seconds"] is None
    else:
        assert calls == ["retrieval", "diagnosis"]
        assert result["retrieval"]["index_id"] == "c" * 64
        assert result["retrieval"]["embedding_identity"] == identity
        assert result["retrieval"]["results"] == [{
            "chunk_id": hit.chunk.chunk_id,
            "score": 0.8,
        }]
        assert result["reference_context"] == build_reference_context([hit])
        assert result["timing"]["diagnosis_seconds"] >= 0

        # Report provenance must not alias the retrieval result.
        identity["model"] = "changed"
        assert (
            result["retrieval"]["embedding_identity"]["model"]
            == "embeddinggemma:300m"
        )

    if failure_stage is None:
        assert result["status"] == "completed"
        assert result["error"] is None
    else:
        assert result["status"] == "failed"
        assert result["error"]["stage"] == failure_stage
        assert result["diagnosis"] is None


def test_replay_rejects_two_reference_sources(tmp_path):
    with pytest.raises(ValueError, match="not both"):
        replay.replay_diagnosis(
            tmp_path / "unused.json",
            reference_hits=[],
            retrieval_connection=object(),
        )


def test_cli_opens_and_closes_database_for_reference_replay(monkeypatch, tmp_path, capsys):
    database_url = "postgresql://test-only"
    monkeypatch.setenv("OPSPILOT_DATABASE_URL", database_url)

    connection = object()
    events = []
    output_dir = tmp_path / "replays"

    @contextmanager
    def fake_connect(url, *, autocommit, connect_timeout):
        assert url == database_url
        assert autocommit is True
        assert connect_timeout == 5
        events.append("open")
        try:
            yield connection
        finally:
            events.append("close")

    def fake_replay(
        path, *, model, settings, retrieval_connection, retrieval_top_k
    ):
        events.append("replay")
        assert retrieval_connection is connection
        assert retrieval_top_k == 2

        return {
            "run_id": "reference-replay",
            "evaluation_mode": "diagnosis_replay",
            "diagnosis_model": model,
            "diagnosis_settings": settings.model_dump(mode="json"),
            "status": "completed",
            "source": {"run_id": "original"},
            "timing": {},
            "error": None,
            "usage": UsageCollector().snapshot(),
        }

    monkeypatch.setattr(replay.psycopg, "connect", fake_connect)
    monkeypatch.setattr(replay, "replay_diagnosis", fake_replay)

    exit_code = replay.main([
        str(tmp_path / "source.json"),
        "--with-references",
        "--retrieval-top-k", "2",
        "--output-dir", str(output_dir),
    ])

    assert exit_code == 0
    assert events == ["open", "replay", "close"]
    assert (output_dir / "reference-replay.json").exists()
    assert database_url not in capsys.readouterr().out


def test_reference_cli_requires_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv("OPSPILOT_DATABASE_URL", raising=False)

    def unexpected_connect(*args, **kwargs):
        pytest.fail("Missing configuration must not open a connection.")

    monkeypatch.setattr(replay.psycopg, "connect", unexpected_connect)

    with pytest.raises(SystemExit) as error:
        replay.main([
            str(tmp_path / "source.json"),
            "--with-references",
        ])

    assert error.value.code == 2


def test_reference_cli_handles_connection_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(
        "OPSPILOT_DATABASE_URL",
        "postgresql://test-only",
    )
    output_dir = tmp_path / "replays"

    def failed_connect(*args, **kwargs):
        raise replay.psycopg.OperationalError("private connection details")

    def unexpected_replay(*args, **kwargs):
        pytest.fail("Replay must not start after connection failure.")

    monkeypatch.setattr(replay.psycopg, "connect", failed_connect)
    monkeypatch.setattr(replay, "replay_diagnosis", unexpected_replay)

    exit_code = replay.main([
        str(tmp_path / "source.json"),
        "--with-references",
        "--output-dir", str(output_dir),
    ])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "PostgreSQL" in output
    assert "private connection details" not in output
    assert not output_dir.exists()
