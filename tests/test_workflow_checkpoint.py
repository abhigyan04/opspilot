import asyncio
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow import build_investigation_graph
from app.agent.settings import DiagnosisSettings
from app.tools.data import SCENARIOS_ROOT


def test_resume_retries_diagnosis_without_repeating_investigation(monkeypatch):
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

    def flaky_diagnose(incident, steps, *, model, settings, usage):
        calls["diagnosis"] += 1
        assert steps == investigation["steps"]

        if calls["diagnosis"] == 1:
            raise ConnectionError("Temporary diagnosis failure.")

        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(prompt_eval_count=20, eval_count=6),
        )
        return diagnosis

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", flaky_diagnose)

    graph = build_investigation_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "diagnosis-recovery-test"}}

    async def check():
        with pytest.raises(ConnectionError, match="Temporary diagnosis failure"):
            await graph.ainvoke(
                {"incident": "Investigate checkout-service."},
                config=config,
            )

        assert calls == {"investigation": 1, "diagnosis": 1}

        checkpoint = await graph.aget_state(config)
        assert checkpoint.values["investigation"] == investigation
        assert "diagnosis" not in checkpoint.values
        assert checkpoint.next == ("diagnose",)
        assert (
            checkpoint.values["usage"]["investigation"]["totals"]["attempts"]
            == 1
        )

        # None resumes pending work instead of submitting a new input.
        result = await graph.ainvoke(None, config=config)

        assert calls == {"investigation": 1, "diagnosis": 2}
        assert result["investigation"] == investigation
        assert result["diagnosis"] == diagnosis.model_dump(mode="json")
        assert result["usage"]["investigation"]["totals"]["input_tokens"] == 10
        assert result["usage"]["diagnosis"]["totals"]["input_tokens"] == 20

        completed = await graph.aget_state(config)
        assert completed.next == ()

    asyncio.run(check())


def test_checkpoint_threads_keep_state_and_resume_isolated(monkeypatch):
    calls = {
        "incident-a": {"investigation": 0, "diagnosis": 0},
        "incident-b": {"investigation": 0, "diagnosis": 0},
    }
    token_counts = {"incident-a": 10, "incident-b": 30}

    async def fake_investigate(incident, *, max_steps, data_dir, usage):
        calls[incident]["investigation"] += 1
        usage.record(
            stage="investigation",
            model="test-investigation",
            response=SimpleNamespace(
                prompt_eval_count=token_counts[incident],
                eval_count=2,
            ),
        )
        return {
            "status": "finished",
            "reason": f"Collected evidence for {incident}.",
            "steps": [{
                "evidence_id": "evidence-001",
                "decision": {
                    "tool": "search_logs",
                    "arguments": {
                        "service": incident,
                        "level": "ERROR",
                    },
                    "reason": "Collect incident-specific logs.",
                },
                "result": [{"message": f"Evidence for {incident}"}],
            }],
        }

    def fake_diagnose(incident, steps, *, model, settings, usage):
        calls[incident]["diagnosis"] += 1

        assert steps[0]["result"] == [
            {"message": f"Evidence for {incident}"}
        ]

        if incident == "incident-a" and calls[incident]["diagnosis"] == 1:
            raise ConnectionError("Thread A diagnosis failed.")

        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(
                prompt_eval_count=token_counts[incident] + 5,
                eval_count=3,
            ),
        )
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": f"More evidence needed for {incident}.",
            "missing_evidence": ["Additional observations"],
        })

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    graph = build_investigation_graph(checkpointer=InMemorySaver())
    config_a = {"configurable": {"thread_id": "thread-a"}}
    config_b = {"configurable": {"thread_id": "thread-b"}}

    async def check():
        with pytest.raises(ConnectionError, match="Thread A diagnosis failed"):
            await graph.ainvoke(
                {"incident": "incident-a"},
                config=config_a,
            )

        pending_a = await graph.aget_state(config_a)
        assert pending_a.next == ("diagnose",)
        assert "diagnosis" not in pending_a.values

        result_b = await graph.ainvoke(
            {"incident": "incident-b"},
            config=config_b,
        )

        # Completing B must not change A's saved state or pending work.
        unchanged_a = await graph.aget_state(config_a)
        assert unchanged_a.values == pending_a.values
        assert unchanged_a.next == ("diagnose",)

        completed_b = await graph.aget_state(config_b)
        assert completed_b.next == ()

        result_a = await graph.ainvoke(None, config=config_a)

        assert calls == {
            "incident-a": {"investigation": 1, "diagnosis": 2},
            "incident-b": {"investigation": 1, "diagnosis": 1},
        }

        for result, incident in [
            (result_a, "incident-a"),
            (result_b, "incident-b"),
        ]:
            assert result["incident"] == incident
            assert result["investigation"]["steps"][0]["result"] == [
                {"message": f"Evidence for {incident}"}
            ]
            assert result["diagnosis"]["reason"] == (
                f"More evidence needed for {incident}."
            )

            usage = result["usage"]
            assert usage["investigation"]["totals"]["attempts"] == 1
            assert usage["diagnosis"]["totals"]["attempts"] == 1
            assert usage["investigation"]["totals"]["input_tokens"] == (
                token_counts[incident]
            )
            assert usage["diagnosis"]["totals"]["input_tokens"] == (
                token_counts[incident] + 5
            )

        # Resuming A must not change B's completed checkpoint.
        unchanged_b = await graph.aget_state(config_b)
        assert unchanged_b.values == completed_b.values
        assert unchanged_b.next == ()

        completed_a = await graph.aget_state(config_a)
        assert completed_a.next == ()

    asyncio.run(check())


@pytest.mark.parametrize(
    "changed",
    [
        {"diagnosis_model": "qwen3:8b"},
        {"diagnosis_settings": DiagnosisSettings(seed=43)},
        {"max_steps": 3},
        {"tool_backend": "mcp"},
        {"data_dir": SCENARIOS_ROOT / "payment_provider_outage"},
        {"service": "other-service"}
    ]
)
def test_resume_rejects_changed_configuration(monkeypatch, changed):
    calls = {"investigation": 0, "diagnosis": 0}

    async def fake_investigate(*args, **kwargs):
        calls["investigation"] += 1
        return {
            "status": "finished",
            "reason": "Test investigation.",
            "steps": [],
        }

    def failing_diagnosis(*args, **kwargs):
        calls["diagnosis"] += 1
        raise ConnectionError("Planned diagnosis failure.")

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", failing_diagnosis)

    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "configuration-test"}}
    original_options = {
        "data_dir": SCENARIOS_ROOT / "checkout_regression",
        "tool_backend": "direct",
        "max_steps": 6,
        "diagnosis_model": "qwen3:4b",
        "diagnosis_settings": DiagnosisSettings(seed=42),
    }

    async def check():
        original = build_investigation_graph(
            checkpointer=saver,
            **original_options,
        )

        with pytest.raises(ConnectionError, match="Planned diagnosis failure"):
            await original.ainvoke(
                {"incident": "Investigate checkout-service."},
                config=config,
            )

        saved = await original.aget_state(config)
        assert saved.next == ("diagnose",)

        rebuilt = build_investigation_graph(
            checkpointer=saver,
            **{**original_options, **changed},
        )

        with pytest.raises(ValueError, match="configuration does not match"):
            await rebuilt.ainvoke(None, config=config)

        # Rejection happens before any further agent call.
        assert calls == {"investigation": 1, "diagnosis": 1}

        after = await rebuilt.aget_state(config)
        assert after.values == saved.values
        assert after.next == ("diagnose",)

    asyncio.run(check())
