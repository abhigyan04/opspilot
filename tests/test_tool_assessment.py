import pytest

from evals.tool_assessment import evaluate_tool_arguments


def step(tool, arguments):
    return {"decision": {"tool": tool, "arguments": arguments}}


@pytest.mark.parametrize("case_id", [
    "checkout_regression",
    "payment_provider_outage",
    "sparse_evidence",
])
def test_expected_log_arguments_match_even_when_result_is_empty(case_id):
    call = step("search_logs", {
        "service": "checkout-service",
        "level": "ERROR",
    })
    call["result"] = []

    result = evaluate_tool_arguments(case_id, [call])

    assert result["argument_match_rate"] == 1.0
    assert result["matching_calls"] == 1


@pytest.mark.parametrize("arguments", [
    {"service": "wrong-service", "level": "ERROR"},
    {"service": "checkout-service", "level": "INFO"},
    {"service": "checkout-service"},
    {"service": "checkout-service", "level": "ERROR", "extra": True},
])
def test_wrong_or_incomplete_arguments_do_not_match(arguments):
    result = evaluate_tool_arguments(
        "checkout_regression",
        [step("search_logs", arguments)],
    )

    assert result["argument_match_rate"] == 0.0
    assert result["assessments"][0]["verdict"] == "not_met"


def test_commit_expectations_are_scenario_specific():
    call = step("get_commit", {
        "commit_hash": "a1b2c3d4e5f6g7h8i9j0",
    })

    assert evaluate_tool_arguments(
        "checkout_regression", [call]
    )["matching_calls"] == 1

    assert evaluate_tool_arguments(
        "payment_provider_outage", [call]
    )["matching_calls"] == 0

    assert evaluate_tool_arguments(
        "sparse_evidence", [call]
    )["matching_calls"] == 0


def test_missing_arguments_are_not_counted_as_correct_or_incorrect():
    result = evaluate_tool_arguments("checkout_regression", [
        {"decision": {"tool": "search_logs"}},
        step("get_deployments", {"service": "checkout-service"}),
    ])

    assert result["calls"] == 2
    assert result["assessable_calls"] == 1
    assert result["unassessable_calls"] == 1
    assert result["argument_match_rate"] == 1.0


def test_no_calls_has_no_argument_match_rate():
    result = evaluate_tool_arguments("checkout_regression", [])

    assert result["calls"] == 0
    assert result["argument_match_rate"] is None


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError, match="No tool expectations"):
        evaluate_tool_arguments("unknown", [])
