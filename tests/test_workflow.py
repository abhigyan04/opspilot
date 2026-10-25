import asyncio

import pytest
from types import SimpleNamespace

from app.agent.usage import UsageCollector
from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.settings import DiagnosisSettings
from app.agent.workflow import build_investigation_graph
from app.agent.schemas import agent_decision_adapter
from app.tools.data import SCENARIOS_ROOT
from app.tools.logs import search_logs


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
        },
        "workflow_config": {
            "version": 1,
            "data_dir": str(tmp_path.resolve()),
            "tool_backend": "direct",
            "max_steps": 3,
            "diagnosis_model": "qwen3:8b",
            "diagnosis_settings": settings.model_dump(mode="json"),
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


@pytest.mark.parametrize(
    "scenario",
    ["checkout_regression", "payment_provider_outage", "sparse_evidence"],
)
def test_graph_investigates_through_real_mcp(monkeypatch, scenario):
    data_dir = SCENARIOS_ROOT / scenario
    expected = search_logs(
        service="checkout-service",
        level="ERROR",
        data_dir=data_dir,
    )
    decisions = iter([
        agent_decision_adapter.validate_python({
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
            "reason": "Collect scenario logs.",
        }),
        agent_decision_adapter.validate_python({
            "tool": "finish",
            "reason": "Scripted investigation completed.",
        }),
    ])
    diagnosis_inputs = []

    def fake_choose(messages, *, usage=None):
        return next(decisions)

    def fake_diagnose(incident, steps, *, model, settings, usage):
        diagnosis_inputs.append(steps)
        assert len(steps) == 1
        assert steps[0]["result"] == expected
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "Diagnosis is stubbed for this transport test.",
            "missing_evidence": ["A real diagnosis assessment"],
        })

    def unexpected_direct(*args, **kwargs):
        pytest.fail("The graph must execute tools through MCP.")

    monkeypatch.setattr(agent, "choose_next_tool", fake_choose)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)
    monkeypatch.setattr(agent, "execute_tool", unexpected_direct)

    graph = build_investigation_graph(
        data_dir=data_dir,
        max_steps=2,
        tool_backend="mcp",
    )
    result = asyncio.run(
        graph.ainvoke({"incident": "Investigate checkout-service."})
    )

    assert result["investigation"]["status"] == "finished"
    assert len(diagnosis_inputs) == 1
    step = result["investigation"]["steps"][0]
    assert step["evidence_id"] == "evidence-001"
    assert step["result"] == expected

    # Model calls are stubbed, so no model usage should be recorded.
    assert result["usage"]["investigation"]["totals"]["attempts"] == 0
    assert result["usage"]["diagnosis"]["totals"]["attempts"] == 0


def test_graph_rejects_unknown_backend():
    with pytest.raises(ValueError, match="tool_backend"):
        build_investigation_graph(tool_backend="unknown")


def test_graph_rejects_custom_mcp_fixture_directory(tmp_path):
    custom_dir = tmp_path / "checkout_regression"

    with pytest.raises(ValueError, match="standard fixture directory"):
        build_investigation_graph(
            data_dir=custom_dir,
            tool_backend="mcp",
        )


def test_graph_rejects_unknown_mcp_scenario():
    with pytest.raises(ValueError, match="Unsupported MCP scenario"):
        build_investigation_graph(
            data_dir=SCENARIOS_ROOT / "unknown",
            tool_backend="mcp",
        )
