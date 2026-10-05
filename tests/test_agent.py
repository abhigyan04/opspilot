import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import agent
from app.agent.schemas import tool_call_adapter


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
    ("query_metrics", {"service": "inventory-service", "metric_name": "latency"}),
    ("get_deployments", {"service": "payment-service"}),
    ("get_commit", {"commit_hash": "b82e5d3"}),
])
def test_model_arguments_are_used_without_hardcoding(monkeypatch, tool, arguments):
    incident = f"Investigate using these known values: {json.dumps(arguments)}"

    def fake_chat(**kwargs):
        assert kwargs["format"] == tool_call_adapter.json_schema()
        assert kwargs["messages"][-1]["content"] == incident
        return SimpleNamespace(message=SimpleNamespace(content=
            json.dumps({"tool": tool, "arguments": arguments, "reason": "Inspect evidence."})
        ))

    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setattr(agent, tool, lambda **kwargs: kwargs)
    decision = agent.choose_next_tool(incident)
    assert agent.execute_tool(decision) == arguments


def test_invalid_model_response_is_rejected(monkeypatch):
    monkeypatch.setattr(agent, "chat", lambda **kwargs: SimpleNamespace(
        message=SimpleNamespace(content=
            '{"tool":"get_commit","arguments":{},"reason":"Guess a commit."}'
        )
    ))
    with pytest.raises(ValidationError):
        agent.choose_next_tool("Investigate checkout-service errors.")
