import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import agent
from app.agent.schemas import tool_call_adapter, agent_decision_adapter, diagnosis_adapter


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
        prefix = "Tool observation:\n"
        assert messages[-1]["content"].startswith(prefix)

        observation = json.loads(
            messages[-1]["content"][len(prefix):]
        )

        assert observation == {
            "evidence_id": "evidence-001",
            "tool": "get_deployments",
            "arguments": {"service": "checkout-service"},
            "result": deployment_result,
        }

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
    assert result["steps"][0]["evidence_id"] == "evidence-001"


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


def test_root_cause_requires_evidence():
    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python({
            "status": "supported",
            "root_cause": {
                "statement": "The deployment caused the regression.",
                "evidence_ids": [],
            },
            "supporting_claims": [],
            "limitations": [],
        })


def test_diagnosis_can_report_insufficient_evidence():
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "Only an elevated error rate was observed.",
        "missing_evidence": [
            "Application error logs",
            "Relevant deployment changes",
        ],
    })

    assert diagnosis.status == "insufficient_evidence"
    assert len(diagnosis.missing_evidence) == 2


@pytest.mark.parametrize(
    "root_ids, supporting_ids",
    [
        (["evidence-999"], ["evidence-001"]),
        (["evidence-001"], ["evidence-999"]),
    ],
)
def test_diagnosis_rejects_unknown_evidence(root_ids, supporting_ids):
    diagnosis = diagnosis_adapter.validate_python({
        "status": "supported",
        "root_cause": {
            "statement": "A customer lookup change caused the errors.",
            "evidence_ids": root_ids,
        },
        "supporting_claims": [{
            "statement": "Errors increased after deployment.",
            "evidence_ids": supporting_ids,
        }],
        "limitations": [],
    })

    with pytest.raises(ValueError, match="evidence-999"):
        agent.validate_diagnosis_evidence(
            diagnosis,
            [{"evidence_id": "evidence-001"}],
        )


def test_diagnosis_accepts_collected_evidence():
    diagnosis = diagnosis_adapter.validate_python({
        "status": "supported",
        "root_cause": {
            "statement": "A customer lookup change caused the errors.",
            "evidence_ids": ["evidence-001", "evidence-002"],
        },
        "supporting_claims": [],
        "limitations": ["The failure has not been reproduced."],
    })

    agent.validate_diagnosis_evidence(
        diagnosis,
        [
            {"evidence_id": "evidence-001"},
            {"evidence_id": "evidence-002"},
        ],
    )


def test_insufficient_evidence_requires_no_citations():
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "No operational evidence was collected.",
        "missing_evidence": ["Application error logs"],
    })

    agent.validate_diagnosis_evidence(diagnosis, [])


@pytest.mark.parametrize(
    "cited_id",
    ["evidence-001", "evidence-999"],
)
def test_generate_diagnosis_validates_model_citations(monkeypatch, cited_id):
    steps = [{
        "evidence_id": "evidence-001",
        "decision": {
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
            "reason": "Earlier model reasoning.",
        },
        "result": [{
            "message": "AttributeError: 'NoneType' object has no attribute 'customer_id'",
        }],
    }]

    payload = {
        "status": "supported",
        "root_cause": {
            "statement": "A customer lookup accessed an attribute on None.",
            "evidence_ids": [cited_id],
        },
        "supporting_claims": [],
        "limitations": ["The failing code path has not been reproduced."],
    }

    def fake_chat(**kwargs):
        assert kwargs["format"] == diagnosis_adapter.json_schema()

        supplied = json.loads(kwargs["messages"][-1]["content"])
        assert supplied == {
            "incident": "Investigate checkout-service.",
            "observations": [{
                "evidence_id": "evidence-001",
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
                "result": steps[0]["result"],
            }],
        }

        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload))
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    if cited_id == "evidence-999":
        with pytest.raises(ValueError, match="evidence-999"):
            agent.generate_diagnosis("Investigate checkout-service.", steps)
    else:
        diagnosis = agent.generate_diagnosis(
            "Investigate checkout-service.", steps
        )
        assert diagnosis.model_dump() == payload


def test_generate_diagnosis_without_evidence_skips_model(monkeypatch):
    def unexpected_chat(**kwargs):
        pytest.fail("No model call is needed when no evidence was collected.")

    monkeypatch.setattr(agent, "chat", unexpected_chat)

    diagnosis = agent.generate_diagnosis(
        "Investigate checkout-service.", []
    )

    assert diagnosis.status == "insufficient_evidence"
    assert diagnosis.missing_evidence
