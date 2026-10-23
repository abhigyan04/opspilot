from dataclasses import replace
from types import SimpleNamespace

import pytest
import json

from evals import runner
from evals.cases import CASES
from app.agent import agent
from app.agent.schemas import agent_decision_adapter, diagnosis_adapter
from app.tools.logs import search_logs
from app.tools.metrics import query_metrics
from app.tools.deployments import get_deployments
from app.tools.git import get_commit


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_run_case_uses_and_records_mcp(monkeypatch, case_id):
    case = CASES[case_id]
    calls = []
    investigation = {
        "status": "finished",
        "reason": "Test completed.",
        "steps": [],
    }

    async def fake_mcp(incident, *, scenario, usage):
        calls.append((incident, usage, scenario))
        return investigation

    def unexpected_direct(*args, **kwargs):
        pytest.fail("Direct investigation must not run.")

    monkeypatch.setattr(runner, "investigate_over_mcp", fake_mcp)
    monkeypatch.setattr(runner, "investigate", unexpected_direct)
    monkeypatch.setattr(
        runner, "evaluate_investigation", lambda *args: {}
    )
    monkeypatch.setattr(
        runner,
        "generate_diagnosis",
        lambda *args, **kwargs: SimpleNamespace(
            model_dump=lambda **kwargs: {
                "status": "insufficient_evidence",
                "reason": "No evidence.",
                "missing_evidence": ["Logs"],
                "reference_notes": [],
            }
        ),
    )

    report = runner.run_case(case, tool_backend="mcp")

    assert report["status"] == "completed"
    assert report["tool_backend"] == "mcp"
    assert report["investigation"] == investigation
    assert len(calls) == 1
    assert calls[0][0] == case.incident
    assert calls[0][1] is not None
    assert calls[0][2] == case_id


def test_mcp_rejects_unsupported_scenario():
    case = replace(CASES["checkout_regression"], case_id="unknown")

    with pytest.raises(ValueError, match="Unsupported MCP scenario"):
        runner.run_case(case, tool_backend="mcp")


def test_mcp_rejects_custom_fixture_directory(tmp_path):
    case = replace(
        CASES["checkout_regression"],
        scenario_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="standard fixture directory"):
        runner.run_case(case, tool_backend="mcp")


def test_run_case_rejects_unknown_backend():
    with pytest.raises(ValueError, match="tool_backend"):
        runner.run_case(
            CASES["checkout_regression"],
            tool_backend="unknown",
        )


def test_mcp_connection_failure_is_recorded(monkeypatch):
    async def failing_mcp(incident, *, scenario, usage):
        raise ConnectionError("Test MCP connection failed.")

    def unexpected_diagnosis(*args, **kwargs):
        pytest.fail("Diagnosis must not run after investigation failure.")

    monkeypatch.setattr(runner, "investigate_over_mcp", failing_mcp)
    monkeypatch.setattr(runner, "generate_diagnosis", unexpected_diagnosis)

    report = runner.run_case(
        CASES["checkout_regression"],
        tool_backend="mcp",
    )

    assert report["status"] == "failed"
    assert report["tool_backend"] == "mcp"
    assert report["error"]["stage"] == "investigation"
    assert report["error"]["type"] == "ConnectionError"
    assert report["investigation"] is None
    assert report["diagnosis"] is None


@pytest.mark.parametrize(
    "arguments, expected",
    [
        ([], "direct"),
        (["--tool-backend", "mcp"], "mcp"),
    ],
)
def test_cli_forwards_tool_backend(monkeypatch, capsys, arguments, expected):
    calls = []

    def fake_batch(case, runs, output_directory, **kwargs):
        calls.append(kwargs["tool_backend"])
        return {
            "tool_backend": kwargs["tool_backend"],
            "summary": {"failed": 0},
        }

    monkeypatch.setattr(runner, "run_batch", fake_batch)

    assert runner.main(arguments) == 0
    assert calls == [expected]
    assert json.loads(capsys.readouterr().out)["tool_backend"] == expected


@pytest.mark.parametrize(
    "arguments",
    [
        ["--tool-backend", "unknown"],
        ["--tool-backend", "mcp", "--case", "unknown"]
    ]
)
def test_invalid_backend_selection_never_starts_batch(monkeypatch, arguments):
    def unexpected_batch(*args, **kwargs):
        pytest.fail("Invalid selection must not start a batch.")

    monkeypatch.setattr(runner, "run_batch", unexpected_batch)

    with pytest.raises(SystemExit) as caught:
        runner.main(arguments)

    assert caught.value.code == 2


@pytest.mark.parametrize("backend", ["direct", "mcp"])
def test_batch_forwards_and_records_backend(monkeypatch, tmp_path, backend):
    calls = []

    def fake_case(case, **kwargs):
        calls.append(kwargs["tool_backend"])
        return {
            "run_id": f"attempt-{len(calls)}",
            "tool_backend": kwargs["tool_backend"],
        }

    monkeypatch.setattr(runner, "run_case", fake_case)
    monkeypatch.setattr(
        runner,
        "summarize_reports",
        lambda reports: {"attempts": len(reports)},
    )

    batch = runner.run_batch(
        CASES["checkout_regression"],
        2,
        tmp_path,
        tool_backend=backend,
    )

    assert calls == [backend, backend]
    assert batch["tool_backend"] == backend

    batch_dir = tmp_path / batch["batch_id"]
    summary = json.loads(
        (batch_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["tool_backend"] == backend

    for filename in batch["report_files"]:
        report = json.loads(
            (batch_dir / filename).read_text(encoding="utf-8")
        )
        assert report["tool_backend"] == backend


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_cli_accepts_supported_mcp_scenarios(case_id):
    args = runner.parse_arguments([
        "--tool-backend", "mcp",
        "--case", case_id,
    ])

    assert args.tool_backend == "mcp"
    assert args.case == case_id


@pytest.mark.parametrize(
    "case_id",
    ["payment_provider_outage", "sparse_evidence"],
)
def test_runner_uses_real_mcp_for_selected_scenario(monkeypatch, case_id):
    case = CASES[case_id]
    service = "checkout-service"

    checks = [
        (
            "search_logs",
            {"service": service, "level": "ERROR"},
            search_logs(
                service=service,
                level="ERROR",
                data_dir=case.scenario_dir,
            ),
        ),
        (
            "query_metrics",
            {"service": service, "metric_name": "error_rate"},
            query_metrics(
                service=service,
                metric_name="error_rate",
                data_dir=case.scenario_dir,
            ),
        ),
        (
            "get_deployments",
            {"service": service},
            get_deployments(service=service, data_dir=case.scenario_dir),
        ),
    ]

    deployments = checks[2][2]
    if deployments:
        commit_hash = deployments[0]["commit_hash"]
        checks.append((
            "get_commit",
            {"commit_hash": commit_hash},
            get_commit(commit_hash=commit_hash, data_dir=case.scenario_dir),
        ))

    # Ensure these fixtures distinguish the scenario from checkout regression.
    if case_id == "sparse_evidence":
        assert checks[0][2] == []
        assert deployments == []
    else:
        assert checks[0][2]
        assert deployments[0]["commit_hash"] == "b72d9e1"

    selections = []

    def scripted_choose(messages, *, usage=None):
        index = len(selections)

        if index:
            prefix = "Tool observation:\n"
            content = messages[-1]["content"]
            assert content.startswith(prefix)
            observation = json.loads(content[len(prefix):])

            previous_tool, previous_arguments, previous_result = checks[index - 1]
            assert observation == {
                "evidence_id": f"evidence-{index:03d}",
                "tool": previous_tool,
                "arguments": previous_arguments,
                "result": previous_result,
            }

        selections.append(True)

        if index == len(checks):
            return agent_decision_adapter.validate_python({
                "tool": "finish",
                "reason": "Scripted investigation completed.",
            })

        tool, arguments, _ = checks[index]
        return agent_decision_adapter.validate_python({
            "tool": tool,
            "arguments": arguments,
            "reason": "Collect scenario evidence.",
        })

    expected_results = [result for _, _, result in checks]
    diagnosis_calls = []

    def fake_diagnosis(incident, steps, **kwargs):
        assert incident == case.incident
        assert [step["result"] for step in steps] == expected_results
        diagnosis_calls.append(True)
        return diagnosis_adapter.validate_python({
            "status": "insufficient_evidence",
            "reason": "Diagnosis is stubbed for this transport test.",
            "missing_evidence": ["A real diagnosis assessment"],
            "reference_notes": [],
        })

    def unexpected_direct(*args, **kwargs):
        pytest.fail("The runner must use MCP execution.")

    monkeypatch.setattr(agent, "choose_next_tool", scripted_choose)
    monkeypatch.setattr(agent, "execute_tool", unexpected_direct)
    monkeypatch.setattr(runner, "investigate", unexpected_direct)
    monkeypatch.setattr(runner, "generate_diagnosis", fake_diagnosis)

    report = runner.run_case(case, tool_backend="mcp")

    assert report["status"] == "completed", report["error"]
    assert report["tool_backend"] == "mcp"
    assert report["case_id"] == case_id
    assert report["investigation"]["status"] == "finished"
    assert len(selections) == len(checks) + 1
    assert diagnosis_calls == [True]
    assert report["metrics"]["required_tool_coverage"] == 1.0

    for index, (step, check) in enumerate(
        zip(report["investigation"]["steps"], checks),
        start=1,
    ):
        tool, arguments, expected = check
        assert step["evidence_id"] == f"evidence-{index:03d}"
        assert step["decision"]["tool"] == tool
        assert step["decision"]["arguments"] == arguments
        assert step["result"] == expected

    assert len(report["investigation"]["steps"]) == len(checks)
