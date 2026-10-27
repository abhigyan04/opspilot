import pytest
from fastapi.testclient import TestClient

import app.main as api


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("checkout_regression", "declined"),
        ("payment_provider_outage", "no_proposal"),
    ],
)
def test_demo_data_is_recorded_and_independent(tmp_path, monkeypatch, scenario, expected_status):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Demo loading must not access live workflows")

    for name in ("start_workflow", "inspect_workflow", "resume_workflow"):
        monkeypatch.setattr(api, name, forbidden)

    database = tmp_path / "missing" / "checkpoints.sqlite"

    with TestClient(api.create_app(database=database)) as client:
        response = client.get(f"/demo-data/{scenario}.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    data = response.json()
    assert data["scenario"] == scenario
    assert data["mode"] == "recorded_demo"
    assert data["synthetic"] is True
    assert data["presentation"]["review_notes"]

    workflow = data["workflow"]
    state = workflow["state"]

    assert workflow["thread_id"] == f"demo-{scenario}"
    assert workflow["next"] == []
    assert workflow["interrupts"] == []
    assert state["proposal_status"] == expected_status
    assert "proposal_id" not in state
    assert "workflow_config" not in state

    evidence_ids = {
        step["evidence_id"]
        for step in state["investigation"]["steps"]
    }
    diagnosis = state["diagnosis"]

    if diagnosis["status"] == "supported":
        claims = [
            diagnosis["root_cause"],
            *diagnosis["supporting_claims"],
        ]
        for claim in claims:
            assert set(claim["evidence_ids"]) <= evidence_ids

    assert not database.parent.exists()


def test_unknown_demo_scenario_returns_404(tmp_path):
    with TestClient(
        api.create_app(database=tmp_path / "checkpoints.sqlite")
    ) as client:
        response = client.get("/demo-data/not-a-demo.json")

    assert response.status_code == 404
    assert response.json() == {"detail": "Demo scenario not found."}


def test_demo_data_rejects_post(tmp_path):
    with TestClient(
        api.create_app(database=tmp_path / "checkpoints.sqlite")
    ) as client:
        response = client.post(
            "/demo-data/checkout_regression.json",
            json={"decision": "approve"},
        )

    assert response.status_code == 405


def test_demo_page_is_available_without_live_workflows(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Demo page must not access live workflows")

    for name in ("start_workflow", "inspect_workflow", "resume_workflow"):
        monkeypatch.setattr(api, name, forbidden)

    database = tmp_path / "missing" / "checkpoints.sqlite"

    with TestClient(api.create_app(database=database)) as client:
        response = client.get("/demo.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    html = response.text
    assert "Recorded demo" in html
    assert 'id="demo-scenario"' in html
    assert 'id="demo-review-notes"' in html
    assert 'id="load-demo"' in html

    for control in (
        "start-workflow",
        "lookup",
        "review-controls",
        "approve",
        "decline",
    ):
        assert f'id="{control}"' not in html

    assert not database.parent.exists()
