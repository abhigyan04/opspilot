import asyncio

import pytest
from fastapi.testclient import TestClient
from uuid import UUID

import app.main as api
from app.agent import agent, workflow
from app.agent.schemas import RollbackProposal, diagnosis_adapter
from app.agent.workflow_cli import inspect_workflow, start_workflow
from app.main import create_app


def test_health_does_not_require_workflow_database(tmp_path):
    database = tmp_path / "missing" / "workflow.sqlite"

    with TestClient(create_app(database=database)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not database.parent.exists()


def test_missing_workflow_database_returns_503(tmp_path):
    database = tmp_path / "missing" / "workflow.sqlite"

    with TestClient(create_app(database=database)) as client:
        response = client.get("/workflows/unknown")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Workflow database is unavailable."
    }
    assert not database.parent.exists()


@pytest.mark.parametrize("with_proposal", [False, True])
def test_get_workflow_preserves_saved_state(tmp_path, monkeypatch, with_proposal):
    async def fake_investigate(*args, **kwargs):
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": [],
        }

    def fake_diagnose(*args, **kwargs):
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "Scripted diagnosis.",
            "missing_evidence": ["Operational observations"],
        })

    # Isolate HTTP inspection from proposal policy.
    proposal = RollbackProposal(
        action="rollback_service",
        service="checkout-service",
        current_version="1.7.4",
        target_version="1.7.3",
        reason="Scripted proposal for API inspection.",
        evidence_ids=["evidence-001"],
    )

    monkeypatch.setattr(agent, "investigate_async", fake_investigate)
    monkeypatch.setattr(agent, "generate_diagnosis", fake_diagnose)
    monkeypatch.setattr(
        workflow,
        "build_rollback_proposal",
        lambda *args, **kwargs: proposal if with_proposal else None,
    )

    database = tmp_path / "workflow.sqlite"
    original = asyncio.run(
        start_workflow(
            database=database,
            thread_id="api-test",
            incident="Investigate checkout-service.",
            scenario="checkout_regression",
            model="qwen3:8b",
            tool_backend="direct",
        )
    )

    def unexpected_call(*args, **kwargs):
        raise AssertionError("HTTP inspection must not execute workflow work.")

    monkeypatch.setattr(agent, "investigate_async", unexpected_call)
    monkeypatch.setattr(agent, "generate_diagnosis", unexpected_call)
    monkeypatch.setattr(
        workflow, "build_rollback_proposal", unexpected_call
    )

    expected = {
        key: value
        for key, value in original.items()
        if key != "database"
    }

    with TestClient(create_app(database=database)) as client:
        first = client.get("/workflows/api-test")
        second = client.get("/workflows/api-test")
        missing = client.get("/workflows/unknown")
        blank = client.get("/workflows/%20")

    assert first.status_code == 200
    assert first.json() == expected
    assert second.status_code == 200
    assert second.json() == expected
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Workflow not found."}
    assert blank.status_code == 422

    persisted = asyncio.run(
        inspect_workflow(database=database, thread_id="api-test")
    )
    assert persisted == original


def test_post_workflow_forwards_request_and_generates_ids(tmp_path, monkeypatch):
    database = tmp_path / "workflow.sqlite"
    calls = []

    async def fake_start(**kwargs):
        calls.append(kwargs)
        return {
            "database": str(kwargs["database"]),
            "thread_id": kwargs["thread_id"],
            "next": [],
            "state": {"proposal_status": "no_proposal"},
            "interrupts": [],
        }

    monkeypatch.setattr(api, "start_workflow", fake_start)

    payload = {
        "incident": "Investigate checkout-service.",
        "scenario": "payment_provider_outage",
        "tool_backend": "mcp",
    }

    with TestClient(create_app(database=database)) as client:
        first = client.post("/workflows", json=payload)
        second = client.post("/workflows", json=payload)

    assert len(calls) == 2
    generated_ids = []

    for response, call in zip((first, second), calls):
        assert response.status_code == 201
        body = response.json()
        thread_id = body["thread_id"]
        generated_ids.append(thread_id)

        assert thread_id.startswith("workflow-")
        assert UUID(thread_id.removeprefix("workflow-")).version == 4
        assert response.headers["Location"] == f"/workflows/{thread_id}"
        assert body == {
            "thread_id": thread_id,
            "next": [],
            "state": {"proposal_status": "no_proposal"},
            "interrupts": [],
        }
        assert call == {
            "database": database.resolve(),
            "thread_id": thread_id,
            "incident": payload["incident"],
            "scenario": "payment_provider_outage",
            "model": "qwen3:8b",
            "tool_backend": "mcp",
        }

    assert generated_ids[0] != generated_ids[1]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"incident": " "},
        {"incident": "Investigate.", "scenario": "unknown"},
        {"incident": "Investigate.", "tool_backend": "remote"},
        {"incident": "Investigate.", "database": "other.sqlite"},
        {"incident": "Investigate.", "thread_id": "existing"},
    ],
)
def test_invalid_post_does_not_start_workflow(tmp_path, monkeypatch, payload):
    database = tmp_path / "missing" / "workflow.sqlite"

    async def unexpected_start(**kwargs):
        raise AssertionError("Invalid requests must not start work.")

    monkeypatch.setattr(api, "start_workflow", unexpected_start)

    with TestClient(create_app(database=database)) as client:
        response = client.post("/workflows", json=payload)

    assert response.status_code == 422
    assert not database.parent.exists()


def test_post_failure_returns_thread_id_without_raw_error(tmp_path, monkeypatch):
    calls = []

    async def failing_start(**kwargs):
        calls.append(kwargs)
        raise ConnectionError("Internal connection details")

    monkeypatch.setattr(api, "start_workflow", failing_start)

    with TestClient(
        create_app(database=tmp_path / "workflow.sqlite")
    ) as client:
        response = client.post(
            "/workflows",
            json={"incident": "Investigate checkout-service."},
        )

    assert response.status_code == 500
    assert len(calls) == 1
    assert response.json() == {
        "detail": {
            "message": (
                "Workflow execution failed. "
                "Inspect this thread for any saved checkpoint."
            ),
            "thread_id": calls[0]["thread_id"],
        }
    }
    assert "Internal connection details" not in response.text
