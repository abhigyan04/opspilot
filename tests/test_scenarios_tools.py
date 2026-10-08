import json
import pytest

from app.tools.deployments import get_deployments
from app.tools.git import get_commit
from app.tools.metrics import query_metrics
from app.tools.logs import search_logs
from app.agent import agent
from app.agent.schemas import agent_decision_adapter


def test_default_logs_work_outside_repository_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    logs = search_logs("checkout-service", "ERROR")

    assert any("AttributeError" in log["message"] for log in logs)


def test_log_scenarios_are_isolated(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    for directory, message in [
        (first, "Customer lookup failed"),
        (second, "Payment provider unavailable"),
    ]:
        (directory / "log.json").write_text(
            json.dumps([{
                "service": "checkout-service",
                "level": "ERROR",
                "message": message,
            }]),
            encoding="utf-8",
        )

    first_logs = search_logs(
        "checkout-service", "ERROR", data_dir=first
    )
    second_logs = search_logs(
        "checkout-service", "ERROR", data_dir=second
    )
    first_again = search_logs(
        "checkout-service", "ERROR", data_dir=first
    )

    assert first_logs[0]["message"] == "Customer lookup failed"
    assert second_logs[0]["message"] == "Payment provider unavailable"
    assert first_again == first_logs


@pytest.mark.parametrize(
    "tool, arguments, filename, record, value_field, first_value, second_value",
    [
        (
            query_metrics,
            ("checkout-service", "error_rate"),
            "metrics.json",
            {"service": "checkout-service", "metric": "error_rate"},
            "value",
            0.4,
            0.01,
        ),
        (
            get_deployments,
            ("checkout-service",),
            "deployments.json",
            {"service": "checkout-service"},
            "version",
            "1.7.4",
            "1.7.3",
        ),
        (
            get_commit,
            ("abc1234",),
            "commits.json",
            {"hash": "abc1234"},
            "diff",
            "Customer lookup changed",
            "Only documentation changed",
        ),
    ],
)
def test_other_tools_keep_scenarios_isolated(tmp_path, tool, arguments, filename, record, value_field, first_value, second_value):
    first = tmp_path / "first"
    second = tmp_path / "second"

    for directory, value in [
        (first, first_value),
        (second, second_value),
    ]:
        directory.mkdir()
        (directory / filename).write_text(
            json.dumps([{**record, value_field: value}]),
            encoding="utf-8",
        )

    def read_value(directory):
        result = tool(*arguments, data_dir=directory)
        row = result[0] if isinstance(result, list) else result
        return row[value_field]

    assert read_value(first) == first_value
    assert read_value(second) == second_value
    assert read_value(first) == first_value


def test_investigation_uses_selected_scenario(monkeypatch, tmp_path):
    expected_logs = [{
        "service": "checkout-service",
        "level": "ERROR",
        "message": "Payment provider unavailable",
    }]
    (tmp_path / "log.json").write_text(
        json.dumps(expected_logs),
        encoding="utf-8",
    )

    decisions = iter([
        agent_decision_adapter.validate_python({
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
            "reason": "Inspect errors.",
        }),
        agent_decision_adapter.validate_python({
            "tool": "finish",
            "reason": "Stop this test investigation.",
        }),
    ])

    monkeypatch.setattr(
        agent,
        "choose_next_tool",
        lambda messages: next(decisions),
    )

    result = agent.investigate(
        "Investigate checkout-service.",
        data_dir=tmp_path,
    )

    assert result["status"] == "finished"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["result"] == expected_logs
