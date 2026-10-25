import asyncio
from copy import deepcopy

import pytest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent import agent
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow import build_investigation_graph
from app.tools.deployments import get_deployments
from app.tools.git import get_commit


@pytest.mark.parametrize(
    "supported, service, expected_status, review_action",
    [
        (True, "checkout-service", "review_required", "approve"),
        (True, "checkout-service", "review_required", "decline"),
        (False, "checkout-service", "no_proposal", None),
        (True, "other-service", "no_proposal", None),
        (True, "checkout-service", "review_required", True),
        (True, "checkout-service", "review_required", ""),
        (True, "checkout-service", "review_required", "approve"),
        (True, "checkout-service", "review_required", "approve wrong-id"),
        (True, "checkout-service", "review_required", "decline wrong-id"),
        (
            True,
            "checkout-service",
            "review_required",
            {"approved": True},
        )
    ]
)
def test_graph_applies_existing_proposal_policy(monkeypatch, supported, service, expected_status, review_action):
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

    calls = []

    async def fake_investigate(*args, **kwargs):
        calls.append("investigate")
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": steps,
        }

    def fake_diagnose(*args, **kwargs):
        calls.append("diagnose")
        return diagnosis

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)

    config = {"configurable": {"thread_id": "proposal-review-test"}}
    graph = build_investigation_graph(
        service=service,
        checkpointer=InMemorySaver(),
    )
    result = asyncio.run(
        graph.ainvoke(
            {"incident": "Investigate checkout-service."},
            config=config,
        )
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
        proposal_id = result["proposal_id"]
        assert isinstance(proposal_id, str)
        assert proposal_id

        interruptions = result["__interrupt__"]
        assert len(interruptions) == 1
        payload = interruptions[0].value
        assert payload["proposal_id"] == proposal_id
        assert payload["proposal"] == proposal
        assert payload["diagnosis"] == diagnosis.model_dump(mode="json")

        pending = asyncio.run(graph.aget_state(config))
        assert pending.next == ("review",)
        assert pending.values["proposal_status"] == "review_required"

        if review_action not in ("approve", "decline"):
            with pytest.raises(
                ValueError,
                match="explicitly approve or decline",
            ):
                asyncio.run(
                    graph.ainvoke(
                        Command(resume=review_action),
                        config=config,
                    )
                )

            rejected = asyncio.run(graph.aget_state(config))

            # No approval or decline was committed.
            assert rejected.values == pending.values
            assert rejected.values["proposal_status"] == "review_required"
            assert rejected.values["proposal_id"] == proposal_id
            assert rejected.values["proposal"] == proposal
            assert rejected.next == ("review",)

            # Earlier work and evidence remain unchanged.
            assert calls == ["investigate", "diagnose"]
            assert steps == original_steps
            return

        resumed = asyncio.run(
            graph.ainvoke(
                Command(resume=f"{review_action} {proposal_id}"),
                config=config,
            )
        )

        assert resumed["proposal_status"] == (
            "approved" if review_action == "approve" else "declined"
        )
        assert resumed["proposal_id"] == proposal_id
        assert resumed["proposal"] == proposal
        assert calls == ["investigate", "diagnose"]
        assert resumed["investigation"]["steps"] == original_steps
        assert steps == original_steps

        completed = asyncio.run(graph.aget_state(config))
        assert completed.next == ()
    else:
        assert result["proposal"] is None
        assert result["proposal_id"] is None
        assert not result.get("__interrupt__")
        completed = asyncio.run(graph.aget_state(config))
        assert completed.next == ()
