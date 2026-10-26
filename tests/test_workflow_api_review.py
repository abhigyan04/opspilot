from copy import deepcopy
import asyncio

from httpx import ASGITransport, AsyncClient
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


@pytest.mark.parametrize(
    "first_decision, second_decision, expected_status",
    [
        ("approve", "decline", "approved"),
        ("decline", "approve", "declined"),
    ],
)
def test_overlapping_reviews_accept_only_first_decision(tmp_path, monkeypatch, first_decision, second_decision, expected_status):
    async def exercise():
        saved = pending_result()
        original = deepcopy(saved)
        inspections = []
        resumes = []

        first_resume_entered = asyncio.Event()
        release_first_resume = asyncio.Event()
        second_request_started = asyncio.Event()

        async def fake_inspect(**kwargs):
            inspections.append(kwargs)
            return deepcopy(saved)

        async def controlled_resume(**kwargs):
            resumes.append(kwargs)
            first_resume_entered.set()
            await release_first_resume.wait()

            decision = kwargs["response"].split(" ", 1)[0]
            saved["state"]["proposal_status"] = {
                "approve": "approved",
                "decline": "declined",
            }[decision]
            saved["next"] = []
            saved["interrupts"] = []
            return deepcopy(saved)

        monkeypatch.setattr(api, "inspect_workflow", fake_inspect)
        monkeypatch.setattr(api, "resume_workflow", controlled_resume)

        application = create_app(
            database=tmp_path / "workflow.sqlite"
        )
        transport = ASGITransport(app=application)
        tasks = []

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            async def submit_second():
                second_request_started.set()
                return await client.post(
                    "/workflows/review-test/review",
                    json={
                        "proposal_id": PROPOSAL_ID,
                        "decision": second_decision,
                    },
                )

            try:
                first = asyncio.create_task(
                    client.post(
                        "/workflows/review-test/review",
                        json={
                            "proposal_id": PROPOSAL_ID,
                            "decision": first_decision,
                        },
                    )
                )
                tasks.append(first)

                # Keep the first request inside resume while the second arrives.
                await asyncio.wait_for(
                    first_resume_entered.wait(), timeout=5
                )

                second = asyncio.create_task(submit_second())
                tasks.append(second)
                await asyncio.wait_for(
                    second_request_started.wait(), timeout=5
                )

                assert not first.done()
                assert not second.done()
                assert len(inspections) == 1
                assert len(resumes) == 1
                assert saved == original

                release_first_resume.set()
                first_response, second_response = await asyncio.wait_for(
                    asyncio.gather(first, second),
                    timeout=5,
                )
            finally:
                release_first_resume.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        assert first_response.status_code == 200
        assert second_response.status_code == 409
        assert second_response.json() == {
            "detail": "Workflow is not waiting for review."
        }

        expected = {
            **original,
            "next": [],
            "interrupts": [],
            "state": {
                **original["state"],
                "proposal_status": expected_status,
            },
        }
        assert first_response.json() == expected
        assert saved == expected

        # The second request checks the updated state but never resumes.
        assert len(inspections) == 2
        assert len(resumes) == 1
        assert resumes[0]["response"] == (
            f"{first_decision} {PROPOSAL_ID}"
        )

    asyncio.run(exercise())
