from copy import deepcopy

import pytest

from evals.evidence_assessment import (
    evaluate_evidence_content,
    expected_results,
)


def complete_steps(case_id):
    return [
        {"decision": {"tool": tool}, "result": result}
        for tool, result in expected_results(case_id).items()
    ]


@pytest.mark.parametrize("case_id, nonempty, empty", [
    ("checkout_regression", 4, 0),
    ("payment_provider_outage", 4, 0),
    ("sparse_evidence", 1, 2),
])
def test_complete_fixture_results_are_captured(case_id, nonempty, empty):
    result = evaluate_evidence_content(case_id, complete_steps(case_id))

    assert result["required_nonempty_results"] == nonempty
    assert result["captured_nonempty_results"] == nonempty
    assert result["nonempty_result_coverage"] == 1.0
    assert result["expected_empty_lookups"] == empty
    assert result["matched_empty_lookups"] == empty


def test_empty_provider_logs_do_not_count_as_captured_evidence():
    steps = complete_steps("payment_provider_outage")
    next(
        step for step in steps
        if step["decision"]["tool"] == "search_logs"
    )["result"] = []

    result = evaluate_evidence_content("payment_provider_outage", steps)

    assert result["captured_nonempty_results"] == 3
    assert result["nonempty_result_coverage"] == 0.75


def test_partial_metric_series_does_not_count_as_complete():
    steps = complete_steps("checkout_regression")
    metrics = next(
        step for step in steps
        if step["decision"]["tool"] == "query_metrics"
    )
    metrics["result"] = metrics["result"][:1]

    result = evaluate_evidence_content("checkout_regression", steps)

    assert result["captured_nonempty_results"] == 3


def test_list_order_and_repeated_calls_do_not_change_coverage():
    steps = complete_steps("payment_provider_outage")
    for step in steps:
        if isinstance(step["result"], list):
            step["result"].reverse()
    steps += deepcopy(steps)

    result = evaluate_evidence_content("payment_provider_outage", steps)

    assert result["captured_nonempty_results"] == 4
    assert len(result["assessments"]) == 4


def test_missing_recorded_result_is_distinct_from_no_call():
    result = evaluate_evidence_content("sparse_evidence", [
        {"decision": {"tool": "search_logs"}},
    ])
    outcomes = {
        item["tool"]: item["outcome"]
        for item in result["assessments"]
    }

    assert outcomes["search_logs"] == "result_not_recorded"
    assert outcomes["get_deployments"] == "not_called"
    assert result["matched_empty_lookups"] == 0


def test_unknown_case_is_rejected():
    with pytest.raises(ValueError, match="No evidence expectations"):
        evaluate_evidence_content("unknown", [])
