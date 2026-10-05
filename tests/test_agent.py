import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import agent
from app.agent.schemas import tool_call_adapter, agent_decision_adapter


def make_call(tool, arguments):
    return tool_call_adapter.validate_python(
        {"tool": tool, "arguments": arguments, "reason": "Inspect evidence."}
    )


@pytest.mark.parametrize("tool, arguments", [
    ("delete_database", {}),
    ("search_logs", {"service": "checkout-service"}),
    ("search_logs", {"service": "checkout-service", "level": "INVALID"}),
    ("query_metrics", {"service": "checkout-service", "metric": "error_rate"}),
    ("get_commit", {"service": "checkout-service"}),
    ("get_deployments", {"service": "checkout-service", "unexpected": True}),
])
def test_invalid_arguments_rejected(tool, arguments):
    with pytest.raises(ValidationError):
        make_call(tool, arguments)


def test_all_tools_execute_with_validated_arguments():
    logs = agent.execute_tool(make_call("search_logs", {
        "service": "checkout-service", "level": "ERROR",
    }))
    assert any("AttributeError:" in log["message"] for log in logs)
    metrics = agent.execute_tool(make_call("query_metrics", {
        "service": "checkout-service", "metric_name": "error_rate",
    }))
    assert metrics[-1]["value"] > 0.3
    deployments = agent.execute_tool(make_call("get_deployments", {
        "service": "checkout-service",
    }))
    commit = agent.execute_tool(make_call("get_commit", {
        "commit_hash": deployments[0]["commit_hash"],
    }))
    assert "request.user.customer_id" in commit["diff"]


@pytest.mark.parametrize("tool, arguments", [
    ("search_logs", {"service": "payment-service", "level": "WARNING"}),
    ("query_metrics", {"service": "inventory-service", "metric_name": "error_rate"}),
    ("get_deployments", {"service": "payment-service"}),
    ("get_commit", {"commit_hash": "b82e5d3"}),
])
def test_model_arguments_are_used_without_hardcoding(monkeypatch, tool, arguments):
    incident = f"Investigate using these known values: {json.dumps(arguments)}"

    def fake_chat(**kwargs):
        assert kwargs["format"] == agent_decision_adapter.json_schema()
        assert kwargs["messages"][-1]["content"] == incident
        return SimpleNamespace(message=SimpleNamespace(content=
            json.dumps({"tool": tool, "arguments": arguments, "reason": "Inspect evidence."})
        ))

    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setattr(agent, tool, lambda **kwargs: kwargs)
    decision = agent.choose_next_tool(messages=[{"role": "system", "content": agent.SYSTEM_PROMPT}, {"role": "user", "content": incident}])
    assert agent.execute_tool(decision) == arguments


def test_invalid_model_response_is_rejected(monkeypatch):
    monkeypatch.setattr(agent, "chat", lambda **kwargs: SimpleNamespace(
        message=SimpleNamespace(content=
            '{"tool":"get_commit","arguments":{},"reason":"Guess a commit."}'
        )
    ))
    with pytest.raises(ValidationError):
        agent.choose_next_tool([{"role": "system", "content": agent.SYSTEM_PROMPT},
                                {"role": "user", "content": "Investigate checkout-service errors."}])


def test_investigation_passes_evidence_to_next_decision(monkeypatch):
    deployment_result = [{"commit_hash": "abc1234"}]
    calls = []

    def fake_choose(messages):
        # Snapshot history: investigate mutates the original list afterward.
        calls.append([message.copy() for message in messages])

        if len(calls) == 1:
            return agent_decision_adapter.validate_python({
                "tool": "get_deployments",
                "arguments": {"service": "checkout-service"},
                "reason": "Inspect recent deployments.",
            })

        previous_decision = json.loads(messages[-2]["content"])
        assert previous_decision["tool"] == "get_deployments"
        assert messages[-2]["role"] == "assistant"
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == (
            "Result from get_deployments:\n"
            + json.dumps(deployment_result)
        )

        return agent_decision_adapter.validate_python({
            "tool": "finish",
            "reason": "Stop after inspecting the returned evidence.",
        })

    monkeypatch.setattr(agent, "choose_next_tool", fake_choose)
    monkeypatch.setattr(
        agent, "get_deployments", lambda service: deployment_result
    )

    result = agent.investigate("Investigate checkout-service.")

    assert result["status"] == "finished"
    assert len(calls) == 2
    assert calls[0][-1]["content"] == "Investigate checkout-service."
    assert len(result["steps"]) == 1
    assert result["steps"][0]["result"] == deployment_result


def test_finish_does_not_execute_a_tool(monkeypatch):
    finish = agent_decision_adapter.validate_python({
        "tool": "finish",
        "reason": "No useful next action.",
    })

    monkeypatch.setattr(agent, "choose_next_tool", lambda messages: finish)

    def unexpected_execution(decision):
        pytest.fail("A finish decision must not execute a tool.")

    monkeypatch.setattr(agent, "execute_tool", unexpected_execution)

    result = agent.investigate("Investigate checkout-service.")

    assert result == {
        "status": "finished",
        "reason": "No useful next action.",
        "steps": [],
    }


def test_investigation_stops_at_step_limit(monkeypatch):
    decision = make_call(
        "get_deployments",
        {"service": "checkout-service"},
    )
    selections = []
    executions = []

    def fake_choose(messages):
        selections.append(True)
        return decision

    def fake_execute(decision):
        executions.append(decision)
        return []

    monkeypatch.setattr(agent, "choose_next_tool", fake_choose)
    monkeypatch.setattr(agent, "execute_tool", fake_execute)

    result = agent.investigate(
        "Investigate checkout-service.",
        max_steps=2,
    )

    assert result["status"] == "step_limit"
    assert len(result["steps"]) == 2
    assert len(selections) == 2
    assert len(executions) == 2
