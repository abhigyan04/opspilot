import asyncio
import json

import pytest

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow_cli import main, start_workflow


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
