import pytest

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
