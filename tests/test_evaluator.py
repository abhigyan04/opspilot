from dataclasses import replace

import pytest

from evals.cases import SPARSE_EVIDENCE
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


def test_correct_arguments_do_not_imply_expected_evidence_was_gathered():
    investigation = {
        "status": "finished",
        "steps": [{
            "decision": {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
            },
            "result": [],
        }],
    }

    result = evaluate_investigation(CHECKOUT_REGRESSION, investigation)

    assert result["required_tool_coverage"] == 0.25
    assert result["tool_arguments"]["status"] == "scored"
    assert result["tool_arguments"]["argument_match_rate"] == 1.0
    assert result["evidence_content"]["status"] == "scored"
    assert result["evidence_content"]["captured_nonempty_results"] == 0

    logs = next(
        item for item in result["evidence_content"]["assessments"]
        if item["tool"] == "search_logs"
    )
    assert logs["outcome"] == "result_mismatch"


def test_sparse_empty_lookup_is_separate_from_nonempty_evidence():
    investigation = {
        "status": "finished",
        "steps": [{
            "decision": {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
            },
            "result": [],
        }],
    }

    result = evaluate_investigation(SPARSE_EVIDENCE, investigation)

    assert result["tool_arguments"]["argument_match_rate"] == 1.0
    assert result["evidence_content"]["matched_empty_lookups"] == 1
    assert result["evidence_content"]["captured_nonempty_results"] == 0


@pytest.mark.parametrize("changed_directory", [False, True])
def test_unregistered_configuration_keeps_basic_coverage_only(tmp_path, changed_directory):
    case = (
        replace(CHECKOUT_REGRESSION, scenario_dir=tmp_path)
        if changed_directory
        else replace(CHECKOUT_REGRESSION, case_id="custom-case")
    )

    result = evaluate_investigation(
        case,
        investigation_with(["search_logs"]),
    )

    assert result["required_tool_coverage"] == 0.25
    assert result["tool_arguments"]["status"] == "not_scored"
    assert result["evidence_content"]["status"] == "not_scored"
