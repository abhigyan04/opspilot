import json
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

WORKER = textwrap.dedent("""
    import asyncio
    import json
    import sys
    from types import SimpleNamespace

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agent import agent
    from app.agent.schemas import diagnosis_adapter
    from app.agent.workflow import build_investigation_graph

    phase, database = sys.argv[1:]
    config = {"configurable": {"thread_id": "process-restart-test"}}
    calls = {"investigation": 0, "diagnosis": 0}

    investigation = {
        "status": "finished",
        "reason": "Collected evidence before process exit.",
        "steps": [{
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
                "reason": "Inspect logs.",
            },
            "result": [{"message": "Persisted test evidence"}],
        }],
    }

    async def fake_investigate(incident, *, max_steps, data_dir, usage, model):
        calls["investigation"] += 1
        if phase == "resume":
            raise AssertionError("Investigation repeated after restart.")
        usage.record(
            stage="investigation",
            model="test",
            response=SimpleNamespace(prompt_eval_count=10, eval_count=4),
        )
        return investigation

    def fake_diagnose(incident, steps, *, model, settings, usage):
        calls["diagnosis"] += 1
        assert incident == "Investigate checkout-service."
        assert steps == investigation["steps"]

        if phase == "start":
            raise ConnectionError("Planned diagnosis failure.")

        usage.record(
            stage="diagnosis",
            model=model,
            response=SimpleNamespace(prompt_eval_count=20, eval_count=6),
        )
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "Test evidence does not establish a cause.",
            "missing_evidence": ["Additional observations"],
        })

    agent.investigate_async = fake_investigate
    agent.generate_diagnosis = fake_diagnose

    async def main():
        async with AsyncSqliteSaver.from_conn_string(database) as saver:
            graph = build_investigation_graph(checkpointer=saver)

            if phase == "start":
                try:
                    await graph.ainvoke(
                        {"incident": "Investigate checkout-service."},
                        config=config,
                    )
                except ConnectionError as error:
                    assert str(error) == "Planned diagnosis failure."
                else:
                    raise AssertionError("Expected diagnosis to fail.")

                saved = await graph.aget_state(config)
                assert saved.next == ("diagnose",)
                assert saved.values["investigation"] == investigation
                assert "diagnosis" not in saved.values
            else:
                saved = await graph.aget_state(config)
                assert saved.next == ("diagnose",)
                assert saved.values["investigation"] == investigation

                result = await graph.ainvoke(None, config=config)
                assert result["investigation"] == investigation
                assert result["diagnosis"]["status"] == "insufficient_evidence"
                assert result["usage"]["investigation"]["totals"]["input_tokens"] == 10
                assert result["usage"]["diagnosis"]["totals"]["input_tokens"] == 20

                saved = await graph.aget_state(config)
                assert saved.next == ()

            summary = {
                "phase": phase,
                "calls": calls,
                "next": list(saved.next),
                "diagnosis_present": "diagnosis" in saved.values,
            }

        # Print only after the database connection has closed.
        print(json.dumps(summary))

    asyncio.run(main())
""")


def test_sqlite_resume_in_separate_process(tmp_path):
    database = tmp_path / "restart.sqlite"

    def run_worker(phase):
        completed = subprocess.run(
            [sys.executable, "-c", WORKER, phase, str(database)],
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
    assert first == {
        "phase": "start",
        "calls": {"investigation": 1, "diagnosis": 1},
        "next": ["diagnose"],
        "diagnosis_present": False,
    }

    second = run_worker("resume")
    assert second == {
        "phase": "resume",
        "calls": {"investigation": 0, "diagnosis": 1},
        "next": [],
        "diagnosis_present": True,
    }
