from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.agent import agent, workflow
from app.agent.schemas import diagnosis_adapter
from app.main import create_app
from app.tools.deployments import get_deployments
from app.tools.git import get_commit


@pytest.mark.parametrize(
    "supported, decision",
    [
        (False, None),
        (True, "approve"),
        (True, "decline"),
    ],
)
def test_post_persists_workflow_for_new_app(tmp_path, monkeypatch, supported, decision):
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
                "statement": (
                    "The deployed customer lookup change is implicated."
                ),
                "evidence_ids": ["evidence-001", "evidence-002"],
            },
            "supporting_claims": [],
            "limitations": [
                "Scripted diagnosis for an API persistence test."
            ],
        })
    else:
        diagnosis = diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "A causal change has not been established.",
            "missing_evidence": [
                "Evidence identifying the failure mechanism"
            ],
        })

    calls = {"investigate": 0, "diagnose": 0, "propose": 0}

    async def fake_investigate(incident, *, max_steps, data_dir, usage, model):
        calls["investigate"] += 1
        assert incident == "Investigate checkout-service."
        assert data_dir.name == "checkout_regression"
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": steps,
        }

    def fake_diagnose(incident, observed_steps, *, model, settings, usage):
        calls["diagnose"] += 1
        assert observed_steps == original_steps
        assert model == "qwen3:8b"
        assert settings.num_ctx == 8192
        assert settings.num_predict == 2048
        return diagnosis

    real_builder = workflow.build_rollback_proposal

    def tracked_builder(*args, **kwargs):
        calls["propose"] += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)
    monkeypatch.setattr(
        workflow, "build_rollback_proposal", tracked_builder
    )

    database = tmp_path / "workflow.sqlite"

    with TestClient(create_app(database=database)) as client:
        response = client.post(
            "/workflows",
            json={"incident": "Investigate checkout-service."},
        )

    assert response.status_code == 201
    assert database.is_file()
    created = response.json()
    location = response.headers["Location"]
    assert location == f"/workflows/{created['thread_id']}"

    state = created["state"]
    assert state["investigation"]["steps"] == original_steps
    assert state["diagnosis"] == diagnosis.model_dump(mode="json")
    assert state["workflow_config"]["diagnosis_model"] == "qwen3:8b"
    assert state["workflow_config"]["tool_backend"] == "direct"
    assert calls == {"investigate": 1, "diagnose": 1, "propose": 1}

    if supported:
        assert state["proposal_status"] == "review_required"
        assert state["proposal_id"]
        assert state["proposal"]["current_version"] == deployment["version"]
        assert (
            state["proposal"]["target_version"]
            == deployment["rollback_target_version"]
        )
        assert created["next"] == ["review"]
        assert len(created["interrupts"]) == 1
        assert (
            created["interrupts"][0]["proposal_id"]
            == state["proposal_id"]
        )
        assert created["interrupts"][0]["proposal"] == state["proposal"]
    else:
        assert state["proposal_status"] == "no_proposal"
        assert state["proposal"] is None
        assert state["proposal_id"] is None
        assert created["next"] == []
        assert created["interrupts"] == []

    def unexpected_work(*args, **kwargs):
        raise AssertionError("Inspection or review repeated workflow work.")

    monkeypatch.setattr(agent, "investigate_async", unexpected_work)
    monkeypatch.setattr(agent, "generate_diagnosis", unexpected_work)
    monkeypatch.setattr(
        workflow, "build_rollback_proposal", unexpected_work
    )

    # A fresh application instance reads the existing SQLite database.
    with TestClient(create_app(database=database)) as reopened_client:
        retrieved = reopened_client.get(location)
        repeated = reopened_client.get(location)

    assert retrieved.status_code == 200
    assert repeated.status_code == 200
    assert retrieved.json() == created
    assert repeated.json() == created
    assert steps == original_steps
    assert calls == {"investigate": 1, "diagnose": 1, "propose": 1}

    review_url = f"{location}/review"

    if not supported:
        with TestClient(create_app(database=database)) as client:
            rejected = client.post(
                review_url,
                json={
                    "proposal_id": "nonexistent-proposal",
                    "decision": "approve",
                },
            )
            unchanged = client.get(location)

        assert rejected.status_code == 409
        assert unchanged.status_code == 200
        assert unchanged.json() == created
        return

    # A stale proposal ID must not change the saved state.
    with TestClient(create_app(database=database)) as client:
        rejected = client.post(
            review_url,
            json={
                "proposal_id": "wrong-proposal-id",
                "decision": decision,
            },
        )
        still_pending = client.get(location)

    assert rejected.status_code == 409
    assert still_pending.status_code == 200
    assert still_pending.json() == created

    payload = {
        "proposal_id": created["state"]["proposal_id"],
        "decision": decision,
    }

    # Review through a new app instance using the real resume function.
    with TestClient(create_app(database=database)) as client:
        reviewed_response = client.post(review_url, json=payload)

    assert reviewed_response.status_code == 200
    reviewed = reviewed_response.json()

    expected_status = {
        "approve": "approved",
        "decline": "declined",
    }[decision]
    expected = {
        **created,
        "next": [],
        "interrupts": [],
        "state": {
            **created["state"],
            "proposal_status": expected_status,
        },
    }
    assert reviewed == expected

    # Reopen again: the decision must persist, and cannot be overwritten.
    opposite_decision = "decline" if decision == "approve" else "approve"

    with TestClient(create_app(database=database)) as client:
        persisted = client.get(location)
        duplicate = client.post(review_url, json=payload)
        opposite = client.post(
            review_url,
            json={
                "proposal_id": payload["proposal_id"],
                "decision": opposite_decision,
            },
        )
        final = client.get(location)

    assert persisted.status_code == 200
    assert persisted.json() == expected
    assert duplicate.status_code == 409
    assert opposite.status_code == 409
    assert final.status_code == 200
    assert final.json() == expected

    assert steps == original_steps
    assert calls == {"investigate": 1, "diagnose": 1, "propose": 1}