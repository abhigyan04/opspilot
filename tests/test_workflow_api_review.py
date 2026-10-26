from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.main as api
from app.agent.workflow_cli import WorkflowNotFoundError
from app.main import create_app


PROPOSAL_ID = "e44d2bcb-d640-4c54-ba6b-2291bb6560b9"


def pending_result():
    return {
        "thread_id": "review-test",
        "next": ["review"],
        "state": {
            "proposal_status": "review_required",
            "proposal_id": PROPOSAL_ID,
            "proposal": {
                "action": "rollback_service",
                "service": "checkout-service",
                "current_version": "1.7.4",
                "target_version": "1.7.3",
            },
        },
        "interrupts": [{
            "kind": "rollback_review",
            "proposal_id": PROPOSAL_ID,
        }],
    }


@pytest.mark.parametrize(
    "decision, expected_status",
    [("approve", "approved"), ("decline", "declined")],
)
def test_review_forwards_explicit_decision_and_rejects_repeat(tmp_path, monkeypatch, decision, expected_status):
    database = tmp_path / "workflow.sqlite"
    saved = pending_result()
    original = deepcopy(saved)
    calls = []

    async def fake_inspect(**kwargs):
        assert kwargs == {
            "database": database.resolve(),
            "thread_id": "review-test",
        }
        return deepcopy(saved)

    async def fake_resume(**kwargs):
        calls.append(kwargs)
        saved["state"]["proposal_status"] = expected_status
        saved["next"] = []
        saved["interrupts"] = []
        return deepcopy(saved)

    monkeypatch.setattr(api, "inspect_workflow", fake_inspect)
    monkeypatch.setattr(api, "resume_workflow", fake_resume)

    payload = {"proposal_id": PROPOSAL_ID, "decision": decision}

    with TestClient(create_app(database=database)) as client:
        response = client.post("/workflows/review-test/review", json=payload)
        repeated = client.post("/workflows/review-test/review", json=payload)

    assert response.status_code == 200
    assert response.json() == saved
    assert saved["state"] == {
        **original["state"],
        "proposal_status": expected_status,
    }
    assert calls == [{
        "database": database.resolve(),
        "thread_id": "review-test",
        "response": f"{decision} {PROPOSAL_ID}",
    }]
    assert repeated.status_code == 409


@pytest.mark.parametrize("condition", ["wrong_id", "completed", "no_proposal"])
def test_conflicting_review_does_not_resume(tmp_path, monkeypatch, condition):
    saved = pending_result()
    proposal_id = PROPOSAL_ID

    if condition == "wrong_id":
        proposal_id = "different-proposal"
    else:
        saved["next"] = []
        saved["interrupts"] = []
        saved["state"]["proposal_status"] = (
            "approved" if condition == "completed" else "no_proposal"
        )
        if condition == "no_proposal":
            saved["state"]["proposal"] = None
            saved["state"]["proposal_id"] = None

    original = deepcopy(saved)

    async def fake_inspect(**kwargs):
        return deepcopy(saved)

    async def unexpected_resume(**kwargs):
        raise AssertionError("Conflicting review must not resume.")

    monkeypatch.setattr(api, "inspect_workflow", fake_inspect)
    monkeypatch.setattr(api, "resume_workflow", unexpected_resume)

    with TestClient(
        create_app(database=tmp_path / "workflow.sqlite")
    ) as client:
        response = client.post(
            "/workflows/review-test/review",
            json={"proposal_id": proposal_id, "decision": "approve"},
        )

    assert response.status_code == 409
    assert saved == original


@pytest.mark.parametrize(
    "error, status",
    [
        (WorkflowNotFoundError("Unknown thread"), 404),
        (FileNotFoundError("Missing database"), 503),
    ],
)
def test_review_lookup_errors(tmp_path, monkeypatch, error, status):
    async def failing_inspect(**kwargs):
        raise error

    async def unexpected_resume(**kwargs):
        raise AssertionError("Lookup failure must not resume.")

    monkeypatch.setattr(api, "inspect_workflow", failing_inspect)
    monkeypatch.setattr(api, "resume_workflow", unexpected_resume)

    with TestClient(
        create_app(database=tmp_path / "workflow.sqlite")
    ) as client:
        response = client.post(
            "/workflows/review-test/review",
            json={"proposal_id": PROPOSAL_ID, "decision": "approve"},
        )

    assert response.status_code == status


def test_invalid_review_is_rejected_before_lookup(tmp_path, monkeypatch):
    async def unexpected_inspect(**kwargs):
        raise AssertionError("Invalid request must not reach lookup.")

    monkeypatch.setattr(api, "inspect_workflow", unexpected_inspect)

    with TestClient(
        create_app(database=tmp_path / "workflow.sqlite")
    ) as client:
        response = client.post(
            "/workflows/review-test/review",
            json={"proposal_id": PROPOSAL_ID, "decision": True},
        )

    assert response.status_code == 422
