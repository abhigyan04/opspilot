import asyncio

import pytest
from types import SimpleNamespace

from app.agent.usage import UsageCollector
from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.settings import DiagnosisSettings
from app.agent.workflow import build_investigation_graph


@pytest.mark.parametrize("status", ["finished", "step_limit"])
def test_graph_passes_investigation_to_diagnosis(monkeypatch, tmp_path, status):
    incident = "Investigate checkout-service."
    steps = [{
        "evidence_id": "evidence-001",
        "decision": {
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
            "reason": "Collect errors.",
        },
        "result": [],
    }]
    investigation = {
        "status": status,
        "reason": "Test investigation.",
        "steps": steps
    }
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No matching logs were returned.",
        "missing_evidence": ["Error details"],
    })
    settings = DiagnosisSettings(seed=43, think=False)
    calls = []

    async def fake_investigate(received_incident, *, max_steps, data_dir, usage):
        calls.append("investigate")
        assert received_incident == incident
        assert max_steps == 3
        assert data_dir == tmp_path
        return investigation

    def fake_diagnose(received_incident, received_steps, *, model, settings, usage):
        calls.append("diagnose")
        assert received_incident == incident
        assert received_steps == steps
        assert model == "qwen3:8b"
        assert settings == DiagnosisSettings(seed=43, think=False)
        return diagnosis

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    graph = build_investigation_graph(
        data_dir=tmp_path,
        max_steps=3,
        diagnosis_model="qwen3:8b",
        diagnosis_settings=settings,
    )
    result = asyncio.run(graph.ainvoke({"incident": incident}))

    assert calls == ["investigate", "diagnose"]
    assert result == {
        "incident": incident,
        "investigation": investigation,
        "diagnosis": diagnosis.model_dump(mode="json"),
        "usage": {
            "investigation": UsageCollector().snapshot(),
            "diagnosis": UsageCollector().snapshot(),
        }
    }


def test_graph_stops_when_investigation_fails(monkeypatch):
    async def failing_investigation(*args, **kwargs):
        raise ConnectionError("Test investigation failed.")

    def unexpected_diagnosis(*args, **kwargs):
        pytest.fail("Diagnosis must not run after investigation failure.")

    monkeypatch.setattr(agent, "investigate_async", failing_investigation)
    monkeypatch.setattr(agent, "generate_diagnosis", unexpected_diagnosis)

    graph = build_investigation_graph()

    with pytest.raises(ConnectionError, match="Test investigation failed"):
        asyncio.run(graph.ainvoke({"incident": "Investigate errors."}))


def test_graph_usage_is_isolated_between_runs(monkeypatch):
    collectors = []

    async def fake_investigate(incident, *, max_steps, data_dir, usage):
        collectors.append(usage)
        usage.record(
            stage="investigation",
            model="test-investigation",
            response=SimpleNamespace(prompt_eval_count=10, eval_count=4),
        )
        return {
            "status": "finished",
            "reason": "Test investigation.",
            "steps": [],
        }

    def fake_diagnose(incident, steps, *, model, settings, usage):
        collectors.append(usage)
        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(prompt_eval_count=20, eval_count=6),
        )
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "No operational evidence.",
            "missing_evidence": ["Logs"],
        })

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    graph = build_investigation_graph()

    async def run_twice():
        first = await graph.ainvoke({"incident": "First incident."})
        second = await graph.ainvoke({"incident": "Second incident."})
        return first, second

    first, second = asyncio.run(run_twice())

    assert len(collectors) == 4
    assert len({id(collector) for collector in collectors}) == 4

    for result in (first, second):
        investigation = result["usage"]["investigation"]
        diagnosis = result["usage"]["diagnosis"]

        assert investigation["totals"]["attempts"] == 1
        assert investigation["totals"]["input_tokens"] == 10
        assert investigation["totals"]["output_tokens"] == 4
        assert investigation["calls"][0]["stage"] == "investigation"

        assert diagnosis["totals"]["attempts"] == 1
        assert diagnosis["totals"]["input_tokens"] == 20
        assert diagnosis["totals"]["output_tokens"] == 6
        assert diagnosis["calls"][0]["stage"] == "diagnosis"

    first["usage"]["investigation"]["calls"].clear()
    assert len(second["usage"]["investigation"]["calls"]) == 1
