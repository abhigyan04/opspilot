from evals.cases import CHECKOUT_REGRESSION
from evals.evaluator import evaluate_investigation


def investigation_with(tools, status="finished"):
    return {
        "status": status,
        "steps": [
            {"decision": {"tool": tool}}
            for tool in tools
        ],
    }


def test_complete_tool_coverage():
    result = evaluate_investigation(
        CHECKOUT_REGRESSION,
        investigation_with([
            "search_logs",
            "get_deployments",
            "get_commit",
            "query_metrics",
        ]),
    )

    assert result["required_tool_coverage"] == 1.0
    assert result["missing_tools"] == []
    assert result["tool_calls"] == 4


def test_repeated_tool_does_not_inflate_coverage():
    result = evaluate_investigation(
        CHECKOUT_REGRESSION,
        investigation_with(["search_logs", "search_logs"]),
    )

    assert result["required_tool_coverage"] == 0.25
    assert result["tool_calls"] == 2
    assert result["missing_tools"] == [
        "get_commit",
        "get_deployments",
        "query_metrics",
    ]


def test_no_calls_has_zero_coverage():
    result = evaluate_investigation(
        CHECKOUT_REGRESSION,
        investigation_with([]),
    )

    assert result["required_tool_coverage"] == 0.0
    assert result["stopped_by_model"] is True


def test_step_limit_is_reported():
    result = evaluate_investigation(
        CHECKOUT_REGRESSION,
        investigation_with(["search_logs"], status="step_limit"),
    )

    assert result["hit_step_limit"] is True
    assert result["stopped_by_model"] is False
