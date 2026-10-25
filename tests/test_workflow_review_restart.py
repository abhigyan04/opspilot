import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

WORKER = textwrap.dedent("""
    import asyncio
    import json
    import sys

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command

    from app.agent import agent, workflow
    from app.agent.schemas import diagnosis_adapter
    from app.tools.deployments import get_deployments
    from app.tools.git import get_commit

    phase, database, action = sys.argv[1:]
    config = {"configurable": {"thread_id": "durable-review-test"}}
    calls = {"investigate": 0, "diagnose": 0, "propose": 0}

    deployments = get_deployments(service="checkout-service")
    commit_hash = deployments[0]["commit_hash"]
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
            "result": get_commit(commit_hash=commit_hash),
        },
    ]

    def record_call(name):
        calls[name] += 1
        assert phase == "start", f"{name} repeated after restart"

    async def fake_investigate(*args, **kwargs):
        record_call("investigate")
        return {
            "status": "finished",
            "reason": "Scripted investigation.",
            "steps": steps,
        }

    def fake_diagnose(*args, **kwargs):
        record_call("diagnose")
        return diagnosis_adapter.validate_python({
            "status": "supported",
            "root_cause": {
                "statement": "The deployed customer lookup change is implicated.",
                "evidence_ids": ["evidence-001", "evidence-002"],
            },
            "supporting_claims": [],
            "limitations": ["Scripted diagnosis for a persistence test."],
        })

    real_builder = workflow.build_rollback_proposal

    def tracked_builder(*args, **kwargs):
        record_call("propose")
        return real_builder(*args, **kwargs)

    agent.investigate_async = fake_investigate
    agent.generate_diagnosis = fake_diagnose
    workflow.build_rollback_proposal = tracked_builder

    async def main():
        async with AsyncSqliteSaver.from_conn_string(database) as saver:
            graph = workflow.build_investigation_graph(checkpointer=saver)

            if phase == "start":
                result = await graph.ainvoke(
                    {"incident": "Investigate checkout-service."},
                    config=config,
                )
                assert result["proposal_status"] == "review_required"
                assert result["proposal"] is not None

                interruptions = result["__interrupt__"]
                assert len(interruptions) == 1
                assert interruptions[0].value["proposal_id"] == result["proposal_id"]
                assert interruptions[0].value["proposal"] == result["proposal"]
            else:
                pending = await graph.aget_state(config)
                assert pending.next == ("review",)
                assert pending.values["proposal_status"] == "review_required"

                before = pending.values
                proposal_id = before["proposal_id"]

                result = await graph.ainvoke(
                    Command(resume=f"{action} {proposal_id}"),
                    config=config,
                )
                expected_status = {
                    "approve": "approved",
                    "decline": "declined",
                }[action]
                assert result["proposal_status"] == expected_status
                assert not result.get("__interrupt__")

                # Review changes only the review status.
                for key in (
                    "proposal_id",
                    "proposal",
                    "investigation",
                    "diagnosis",
                    "usage",
                    "workflow_config",
                ):
                    assert result[key] == before[key]

            saved = await graph.aget_state(config)
            expected_next = ("review",) if phase == "start" else ()
            assert saved.next == expected_next
            assert saved.values["investigation"]["steps"] == steps

            summary = {
                "calls": calls,
                "next": list(saved.next),
                "state": saved.values,
            }

        # Emit the result after closing SQLite.
        print(json.dumps(summary))

    asyncio.run(main())
""")


@pytest.mark.parametrize(
    "action, expected_status",
    [("approve", "approved"), ("decline", "declined")],
)
def test_review_survives_process_restart(tmp_path, action, expected_status):
    database = tmp_path / "review.sqlite"

    def run_worker(phase):
        completed = subprocess.run(
            [sys.executable, "-c", WORKER, phase, str(database), action],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, (
            f"Phase: {phase}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        return json.loads(completed.stdout)

    first = run_worker("start")
    assert database.is_file()
    assert first["calls"] == {"investigate": 1, "diagnose": 1, "propose": 1}
    assert first["next"] == ["review"]
    assert first["state"]["proposal_status"] == "review_required"
    assert first["state"]["proposal_id"]

    second = run_worker("resume")
    assert second["calls"] == {"investigate": 0, "diagnose": 0, "propose": 0}
    assert second["next"] == []

    expected_state = {
        **first["state"],
        "proposal_status": expected_status,
    }
    assert second["state"] == expected_state
