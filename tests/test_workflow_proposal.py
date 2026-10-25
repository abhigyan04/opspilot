import asyncio
from copy import deepcopy

import pytest

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow import build_investigation_graph
from app.tools.deployments import get_deployments
from app.tools.git import get_commit


@pytest.mark.parametrize(
    "supported, service, expected_status",
    [
        (True, "checkout-service", "review_required"),
        (False, "checkout-service", "no_proposal"),
        (True, "other-service", "no_proposal"),
    ],
)
def test_graph_applies_existing_proposal_policy(monkeypatch, supported, service, expected_status):
    deployments = get_deployments(service="checkout-service")
    assert len(deployments) == 1
    deployment = deployments[0]
    commit_hash = deployment["commit_hash"]
    commit = get_commit(commit_hash=commit_hash)
    assert commit is not None

    steps = [
        {
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "get_deployments",
                "arguments": {"service": "checkout-service"},
                "reason": "Inspect deployments.",
            },
            "result": deployments,
        },
        {
            "evidence_id": "evidence-002",
            "decision": {
                "tool": "get_commit",
                "arguments": {"commit_hash": commit_hash},
                "reason": "Inspect the deployed change.",
            },
            "result": commit,
        },
    ]
    original_steps = deepcopy(steps)

    if supported:
        diagnosis = diagnosis_adapter.validate_python({
            "status": "supported",
            "root_cause": {
                "statement": "The deployed customer lookup change is implicated.",
                "evidence_ids": ["evidence-001", "evidence-002"],
            },
            "supporting_claims": [],
            "limitations": ["This diagnosis is scripted for an orchestration test."],
        })
    else:
        diagnosis = diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "A causal change has not been established.",
            "missing_evidence": ["Evidence identifying the failure mechanism"],
        })

    async def fake_investigate(*args, **kwargs):
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": steps,
        }

    def fake_diagnose(*args, **kwargs):
        return diagnosis

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    graph = build_investigation_graph(service=service)
    result = asyncio.run(
        graph.ainvoke({"incident": "Investigate checkout-service."})
    )

    assert result["proposal_status"] == expected_status
    assert result["workflow_config"]["service"] == service
    assert result["investigation"]["steps"] == original_steps
    assert steps == original_steps

    if expected_status == "review_required":
        proposal = result["proposal"]
        assert proposal["action"] == "rollback_service"
        assert proposal["service"] == service
        assert proposal["current_version"] == deployment["version"]
        assert proposal["target_version"] == deployment["rollback_target_version"]
        assert set(proposal["evidence_ids"]) == {
            "evidence-001",
            "evidence-002",
        }
    else:
        assert result["proposal"] is None
