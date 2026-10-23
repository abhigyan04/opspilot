from dataclasses import replace
from types import SimpleNamespace

import pytest
import json

from evals import runner
from evals.cases import CASES


def test_run_case_uses_and_records_mcp(monkeypatch):
    case = CASES["checkout_regression"]
    calls = []
    investigation = {
        "status": "finished",
        "reason": "Test completed.",
        "steps": [],
    }

    async def fake_mcp(incident, *, usage):
        calls.append((incident, usage))
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


@pytest.mark.parametrize(
    "case_id",
    ["payment_provider_outage", "sparse_evidence"],
)
def test_mcp_rejects_unsupported_scenario(case_id):
    with pytest.raises(ValueError, match="default checkout_regression"):
        runner.run_case(CASES[case_id], tool_backend="mcp")


def test_mcp_rejects_custom_fixture_directory(tmp_path):
    case = replace(
        CASES["checkout_regression"],
        scenario_dir=tmp_path,
    )

    with pytest.raises(ValueError, match="default checkout_regression"):
        runner.run_case(case, tool_backend="mcp")


def test_run_case_rejects_unknown_backend():
    with pytest.raises(ValueError, match="tool_backend"):
        runner.run_case(
            CASES["checkout_regression"],
            tool_backend="unknown",
        )


def test_mcp_connection_failure_is_recorded(monkeypatch):
    async def failing_mcp(incident, *, usage):
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
        ["--tool-backend", "mcp", "--case", "payment_provider_outage"],
        ["--tool-backend", "mcp", "--case", "sparse_evidence"],
    ],
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
