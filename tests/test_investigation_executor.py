import asyncio

import pytest
import json

from app.mcp_server.client import connect_local_tools
from app.tools.deployments import get_deployments
from app.tools.git import get_commit
from app.agent import agent
from app.agent.schemas import agent_decision_adapter


def deployment_decision():
    return agent_decision_adapter.validate_python({
        "tool": "get_deployments",
        "arguments": {"service": "checkout-service"},
        "reason": "Inspect deployments.",
    })


def test_investigation_uses_async_executor(monkeypatch):
    decision = deployment_decision()
    finish = agent_decision_adapter.validate_python({
        "tool": "finish",
        "reason": "Evidence collected.",
    })
    decisions = iter([decision, finish])
    calls = []
    expected = [{"service": "checkout-service", "version": "test-version"}]

    monkeypatch.setattr(
        agent,
        "choose_next_tool",
        lambda messages, *, usage=None: next(decisions),
    )

    def unexpected_direct_execution(*args, **kwargs):
        pytest.fail("Direct execution must not run with a custom executor.")

    monkeypatch.setattr(agent, "execute_tool", unexpected_direct_execution)

    async def executor(selected):
        calls.append(selected)
        return expected

    result = asyncio.run(
        agent.investigate_async(
            "Investigate checkout-service.",
            tool_executor=executor,
        )
    )

    assert calls == [decision]
    assert result["status"] == "finished"
    assert result["steps"] == [{
        "evidence_id": "evidence-001",
        "decision": decision.model_dump(),
        "result": expected,
    }]


def test_investigation_propagates_executor_failure(monkeypatch):
    decision = deployment_decision()
    failure = ConnectionError("Test connection closed.")

    monkeypatch.setattr(
        agent,
        "choose_next_tool",
        lambda messages, *, usage=None: decision,
    )

    async def executor(selected):
        raise failure

    with pytest.raises(ConnectionError) as caught:
        asyncio.run(
            agent.investigate_async(
                "Investigate checkout-service.",
                tool_executor=executor,
            )
        )

    assert caught.value is failure


def test_investigation_over_mcp(monkeypatch):
    incident = "Investigate checkout-service."
    expected_deployments = get_deployments(service="checkout-service")
    assert expected_deployments

    expected_hash = expected_deployments[0]["commit_hash"]
    expected_commit = get_commit(commit_hash=expected_hash)
    assert expected_commit is not None

    selections = []

    def latest_observation(messages):
        message = messages[-1]
        assert message["role"] == "user"
        prefix = "Tool observation:\n"
        assert message["content"].startswith(prefix)
        return json.loads(message["content"][len(prefix):])

    def scripted_choose(messages, *, usage=None):
        selections.append(True)

        if len(selections) == 1:
            assert messages[-1]["content"] == incident
            return deployment_decision()

        if len(selections) == 2:
            observation = latest_observation(messages)
            assert observation["evidence_id"] == "evidence-001"
            assert observation["tool"] == "get_deployments"
            assert observation["result"] == expected_deployments

            # Construct the next call from evidence received through MCP.
            commit_hash = observation["result"][0]["commit_hash"]
            return agent_decision_adapter.validate_python({
                "tool": "get_commit",
                "arguments": {"commit_hash": commit_hash},
                "reason": "Inspect the deployed commit.",
            })

        if len(selections) == 3:
            observation = latest_observation(messages)
            assert observation["evidence_id"] == "evidence-002"
            assert observation["tool"] == "get_commit"
            assert observation["result"] == expected_commit

            return agent_decision_adapter.validate_python({
                "tool": "finish",
                "reason": "Collected deployment and commit evidence.",
            })

        pytest.fail("Investigation continued after finish.")

    def unexpected_direct_execution(*args, **kwargs):
        pytest.fail("Investigation must execute tools through MCP.")

    monkeypatch.setattr(agent, "choose_next_tool", scripted_choose)
    monkeypatch.setattr(agent, "execute_tool", unexpected_direct_execution)

    async def check():
        async with connect_local_tools() as executor:
            return await agent.investigate_async(
                incident,
                max_steps=3,
                tool_executor=executor.execute,
            )

    result = asyncio.run(check())

    assert result["status"] == "finished"
    assert len(selections) == 3
    assert len(result["steps"]) == 2
    assert [step["evidence_id"] for step in result["steps"]] == [
        "evidence-001",
        "evidence-002",
    ]
    assert result["steps"][0]["result"] == expected_deployments
    assert result["steps"][1]["result"] == expected_commit
