import pytest
from types import SimpleNamespace

from app.agent.usage import UsageCollector
from evals.summary import summarize_reports


def make_report(status, coverage=None, stage=None):
    return {
        "report_version": 2,
        "case_id": "checkout_regression",
        "status": status,
        "metrics": (
            {"required_tool_coverage": coverage}
            if coverage is not None
            else None
        ),
        "timing": {"total_seconds": 10.0},
        "error": {"stage": stage} if stage else None,
    }


def test_summary_includes_failures_and_exposes_coverage_count():
    result = summarize_reports([
        make_report("completed", coverage=1.0),
        make_report("failed", stage="investigation"),
        make_report("failed", coverage=0.5, stage="diagnosis"),
    ])

    assert result["attempts"] == 3
    assert result["completed"] == 1
    assert result["failed"] == 2
    assert result["pipeline_completion_rate"] == pytest.approx(1 / 3)
    assert result["mean_total_seconds"] == 10.0
    assert result["coverage_observations"] == 2
    assert result["mean_required_tool_coverage"] == 0.75
    assert result["failure_stages"] == {
        "investigation": 1,
        "diagnosis": 1,
    }
    assert result["diagnosis_accuracy"] is None


def test_all_failed_investigations_have_unavailable_coverage():
    result = summarize_reports([
        make_report("failed", stage="investigation"),
    ])

    assert result["pipeline_completion_rate"] == 0.0
    assert result["coverage_observations"] == 0
    assert result["mean_required_tool_coverage"] is None


def test_empty_summary_is_rejected():
    with pytest.raises(ValueError, match="At least one"):
        summarize_reports([])


@pytest.mark.parametrize("change, message", [
    ({"report_version": 1}, "version 2"),
    ({"case_id": "different_case"}, "one evaluation case"),
    ({"status": "running"}, "finished reports"),
])
def test_incompatible_reports_are_rejected(change, message):
    changed = make_report("completed", coverage=1.0)
    changed.update(change)

    with pytest.raises(ValueError, match=message):
        summarize_reports([
            make_report("completed", coverage=1.0),
            changed,
        ])


def usage_snapshot(input_tokens, output_tokens):
    usage = UsageCollector()
    usage.record(
        stage="diagnosis",
        model="qwen3:8b",
        response=SimpleNamespace(
            prompt_eval_count=input_tokens,
            eval_count=output_tokens,
        ),
    )
    return usage.snapshot()


def test_summary_counts_usage_from_completed_and_failed_runs():
    completed = make_report("completed", coverage=1.0)
    completed["usage"] = usage_snapshot(100, 20)

    failed = make_report("failed", stage="diagnosis")
    failed["usage"] = usage_snapshot(200, 40)

    usage = summarize_reports([completed, failed])["usage"]

    assert usage == {
        "reports_with_usage": 2,
        "reports_without_usage": 0,
        "recorded_model_attempts": 2,
        "input_counted_calls": 2,
        "known_input_tokens": 300,
        "input_tokens": 300,
        "output_counted_calls": 2,
        "known_output_tokens": 60,
        "output_tokens": 60,
    }


def test_summary_preserves_partial_usage_without_complete_total():
    completed = make_report("completed")
    completed["usage"] = usage_snapshot(100, 20)

    failed = make_report("failed", stage="diagnosis")
    failed["usage"] = usage_snapshot(200, None)

    usage = summarize_reports([completed, failed])["usage"]

    assert usage["input_tokens"] == 300
    assert usage["output_tokens"] is None
    assert usage["known_output_tokens"] == 20
    assert usage["output_counted_calls"] == 1
    assert usage["recorded_model_attempts"] == 2


def test_legacy_report_does_not_count_as_zero_usage():
    legacy = make_report("completed")
    current = make_report("completed")
    current["usage"] = usage_snapshot(100, 20)

    usage = summarize_reports([legacy, current])["usage"]

    assert usage["reports_with_usage"] == 1
    assert usage["reports_without_usage"] == 1
    assert usage["recorded_model_attempts"] == 1
    assert usage["known_input_tokens"] == 100
    assert usage["known_output_tokens"] == 20
    assert usage["input_tokens"] is None
    assert usage["output_tokens"] is None


def test_explicit_zero_attempts_are_distinct_from_missing_usage():
    report = make_report("completed")
    report["usage"] = UsageCollector().snapshot()

    usage = summarize_reports([report])["usage"]

    assert usage["reports_with_usage"] == 1
    assert usage["reports_without_usage"] == 0
    assert usage["recorded_model_attempts"] == 0
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
