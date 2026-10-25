import asyncio
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow import build_investigation_graph


def test_sqlite_resume_after_reopening_storage(monkeypatch, tmp_path):
    database_path = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "sqlite-recovery-test"}}
    calls = {"investigation": 0, "diagnosis": 0}

    investigation = {
        "status": "finished",
        "reason": "Collected available evidence.",
        "steps": [{
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
                "reason": "Inspect logs.",
            },
            "result": [],
        }],
    }
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No matching error logs were returned.",
        "missing_evidence": ["Error details"],
    })

    async def fake_investigate(incident, *, max_steps, data_dir, usage):
        calls["investigation"] += 1
        usage.record(
            stage="investigation",
            model="test-investigation",
            response=SimpleNamespace(prompt_eval_count=10, eval_count=4),
        )
        return investigation

    def failing_diagnosis(*args, **kwargs):
        calls["diagnosis"] += 1
        raise ConnectionError("Diagnosis unavailable.")

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", failing_diagnosis)

    async def first_session():
        async with AsyncSqliteSaver.from_conn_string(
            str(database_path)
        ) as saver:
            graph = build_investigation_graph(checkpointer=saver)

            with pytest.raises(ConnectionError, match="Diagnosis unavailable"):
                await graph.ainvoke(
                    {"incident": "Investigate checkout-service."},
                    config=config,
                )

            checkpoint = await graph.aget_state(config)
            assert checkpoint.next == ("diagnose",)
            assert checkpoint.values["investigation"] == investigation

    asyncio.run(first_session())

    assert database_path.is_file()
    assert calls == {"investigation": 1, "diagnosis": 1}

    # The first graph, connection, and event loop are no longer in use.
    async def unexpected_investigation(*args, **kwargs):
        pytest.fail("Reopening storage must not repeat investigation.")

    def successful_diagnosis(incident, steps, *, model, settings, usage):
        calls["diagnosis"] += 1
        assert incident == "Investigate checkout-service."
        assert steps == investigation["steps"]

        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(prompt_eval_count=20, eval_count=6),
        )
        return diagnosis

    monkeypatch.setattr(agent, "investigate_async", unexpected_investigation)
    monkeypatch.setattr(agent, "generate_diagnosis", successful_diagnosis)

    async def second_session():
        async with AsyncSqliteSaver.from_conn_string(
            str(database_path)
        ) as saver:
            graph = build_investigation_graph(checkpointer=saver)

            checkpoint = await graph.aget_state(config)
            assert checkpoint.next == ("diagnose",)
            assert checkpoint.values["investigation"] == investigation
            assert "diagnosis" not in checkpoint.values

            result = await graph.ainvoke(None, config=config)

            assert result["investigation"] == investigation
            assert result["diagnosis"] == diagnosis.model_dump(mode="json")
            assert (
                result["usage"]["investigation"]["totals"]["input_tokens"]
                == 10
            )
            assert result["usage"]["diagnosis"]["totals"]["input_tokens"] == 20

            completed = await graph.aget_state(config)
            assert completed.next == ()

    asyncio.run(second_session())

    assert calls == {"investigation": 1, "diagnosis": 2}

    # Reopen once more to verify the completed state was also persisted.
    async def third_session():
        async with AsyncSqliteSaver.from_conn_string(
            str(database_path)
        ) as saver:
            graph = build_investigation_graph(checkpointer=saver)
            completed = await graph.aget_state(config)

            assert completed.next == ()
            assert completed.values["diagnosis"] == diagnosis.model_dump(
                mode="json"
            )

    asyncio.run(third_session())
