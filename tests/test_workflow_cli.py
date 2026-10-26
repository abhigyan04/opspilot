import asyncio
import json

import pytest

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow_cli import main, start_workflow
from app.agent import workflow
from app.agent.schemas import RollbackProposal
from app.agent.workflow_cli import inspect_workflow


def test_start_cli_persists_result_and_rejects_existing_thread(tmp_path, monkeypatch, capsys):
    calls = []

    async def fake_investigate(*args, **kwargs):
        calls.append("investigate")
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": [],
        }

    def fake_diagnose(*args, **kwargs):
        calls.append("diagnose")
        assert kwargs["model"] == "qwen3:8b"
        assert kwargs["settings"].num_ctx == 8192
        assert kwargs["settings"].num_predict == 2048
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No operational evidence was collected.",
            "missing_evidence": ["Operational observations"],
        })

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    database = tmp_path / "nested" / "workflow.sqlite"
    arguments = [
        "start",
        "--database", str(database),
        "--thread-id", "cli-test",
        "--incident", "Investigate checkout-service.",
    ]

    main(arguments)
    result = json.loads(capsys.readouterr().out)

    assert database.is_file()
    assert result["database"] == str(database.resolve())
    assert result["thread_id"] == "cli-test"
    assert result["next"] == []
    assert result["interrupts"] == []
    assert result["state"]["proposal_status"] == "no_proposal"
    assert result["state"]["workflow_config"]["diagnosis_model"] == "qwen3:8b"
    assert calls == ["investigate", "diagnose"]

    # A second invocation must not rerun or replace the saved workflow.
    with pytest.raises(ValueError, match="already exists"):
        main(arguments)

    assert calls == ["investigate", "diagnose"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"thread_id": " "},
        {"incident": " "},
        {"scenario": "unknown"},
        {"model": " "},
        {"tool_backend": "unknown"},
    ],
)
def test_invalid_start_does_not_create_database(tmp_path, overrides):
    database = tmp_path / "not-created" / "workflow.sqlite"
    arguments = {
        "database": database,
        "thread_id": "test-thread",
        "incident": "Investigate checkout-service.",
        "scenario": "checkout_regression",
        "model": "qwen3:8b",
        "tool_backend": "direct",
        **overrides,
    }

    with pytest.raises(ValueError):
        asyncio.run(start_workflow(**arguments))

    assert not database.parent.exists()


@pytest.mark.parametrize("with_proposal", [False, True])
def test_inspect_preserves_saved_workflow(
    tmp_path, monkeypatch, capsys, with_proposal
):
    async def fake_investigate(*args, **kwargs):
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": [],
        }

    def fake_diagnose(*args, **kwargs):
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "Scripted diagnosis.",
            "missing_evidence": ["Operational observations"],
        })

    proposal = RollbackProposal(
        action="rollback_service",
        service="checkout-service",
        current_version="1.7.4",
        target_version="1.7.3",
        reason="Scripted proposal for inspection testing.",
        evidence_ids=["evidence-001"],
    )

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)
    monkeypatch.setattr(
        workflow,
        "build_rollback_proposal",
        lambda *args, **kwargs: proposal if with_proposal else None,
    )

    database = tmp_path / "workflow.sqlite"
    original = asyncio.run(
        start_workflow(
            database=database,
            thread_id="inspect-test",
            incident="Investigate checkout-service.",
            scenario="checkout_regression",
            model="qwen3:8b",
            tool_backend="direct",
        )
    )

    def unexpected_call(*args, **kwargs):
        raise AssertionError("Inspection must not execute workflow work.")

    monkeypatch.setattr(agent, "investigate_async", unexpected_call)
    monkeypatch.setattr(agent, "generate_diagnosis", unexpected_call)
    monkeypatch.setattr(
        workflow, "build_rollback_proposal", unexpected_call
    )

    arguments = [
        "inspect",
        "--database", str(database),
        "--thread-id", "inspect-test",
    ]

    main(arguments)
    first = json.loads(capsys.readouterr().out)
    assert first == original

    main(arguments)
    second = json.loads(capsys.readouterr().out)
    assert second == first

    if with_proposal:
        assert first["next"] == ["review"]
        assert first["state"]["proposal_status"] == "review_required"
        assert len(first["interrupts"]) == 1
        assert (
            first["interrupts"][0]["proposal_id"]
            == first["state"]["proposal_id"]
        )
    else:
        assert first["next"] == []
        assert first["interrupts"] == []

    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(
            inspect_workflow(database=database, thread_id="unknown")
        )


def test_inspect_missing_database_does_not_create_it(tmp_path):
    database = tmp_path / "missing" / "workflow.sqlite"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        asyncio.run(
            inspect_workflow(database=database, thread_id="test")
        )

    assert not database.parent.exists()


def test_inspect_rejects_blank_thread_id(tmp_path):
    database = tmp_path / "workflow.sqlite"

    with pytest.raises(ValueError, match="nonblank thread ID"):
        asyncio.run(
            inspect_workflow(database=database, thread_id=" ")
        )

    assert not database.exists()
