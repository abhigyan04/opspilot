import json

import pytest

from evals.assessment import DiagnosisReview, save_review
from evals.review_summary import CRITERION_NAMES, summarize_reviews, summarize_batch_reviews


def make_run(tmp_path, run_id, verdict=None, case_id="checkout_regression"):
    report_path = tmp_path / f"{run_id}.json"
    report_path.write_text(
        json.dumps({
            "report_version": 2,
            "run_id": run_id,
            "case_id": case_id,
            "status": "completed",
            "diagnosis": {
                "status": "insufficient_evidence",
                "reason": "More evidence needed.",
                "missing_evidence": ["Application logs"],
            },
        }),
        encoding="utf-8",
    )

    if verdict is not None:
        review = DiagnosisReview.model_validate({
            "run_id": run_id,
            "case_id": case_id,
            "reviewer": "Test reviewer",
            **{
                name: {
                    "verdict": verdict,
                    "rationale": "Synthetic assessment for aggregation testing.",
                }
                for name in CRITERION_NAMES
            },
        })
        save_review(review, report_path)

    return report_path


def test_summary_keeps_review_and_assessment_counts_separate(tmp_path):
    paths = [
        make_run(tmp_path, "first", "met"),
        make_run(tmp_path, "second", "not_met"),
        make_run(tmp_path, "third", "not_assessable"),
        make_run(tmp_path, "fourth"),
    ]

    result = summarize_reviews(paths)

    assert result["total_runs"] == 4
    assert result["reviewed_runs"] == 3
    assert result["unreviewed_runs"] == 1

    for criterion in result["criteria"].values():
        assert criterion == {
            "met": 1,
            "not_met": 1,
            "not_assessable": 1,
            "assessable": 2,
            "met_rate": 0.5,
        }


def test_unreviewed_run_has_no_criterion_rate(tmp_path):
    result = summarize_reviews([make_run(tmp_path, "unreviewed")])

    assert result["reviewed_runs"] == 0
    assert result["unreviewed_runs"] == 1
    assert result["criteria"]["causal_explanation"]["met_rate"] is None


def test_invalid_review_is_not_silently_skipped(tmp_path):
    path = make_run(tmp_path, "changed", "met")
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="hash"):
        summarize_reviews([path])


def test_duplicate_run_is_rejected(tmp_path):
    path = make_run(tmp_path, "duplicate")

    with pytest.raises(ValueError, match="Duplicate"):
        summarize_reviews([path, path])


def test_mixed_cases_are_rejected(tmp_path):
    first = make_run(tmp_path, "first", case_id="checkout_regression")
    second = make_run(tmp_path, "second", case_id="payment_provider_outage")

    with pytest.raises(ValueError, match="one evaluation case"):
        summarize_reviews([first, second])


def test_empty_report_list_is_rejected():
    with pytest.raises(ValueError, match="At least one"):
        summarize_reviews([])


def write_manifest(tmp_path, filenames, *, case_id="checkout_regression", attempts=1):
    manifest = {
        "batch_id": "test-batch",
        "report_files": filenames,
        "summary": {
            "case_id": case_id,
            "attempts": attempts,
        },
    }
    (tmp_path / "summary.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_batch_summary_loads_only_listed_run_reports(tmp_path):
    path = make_run(tmp_path, "listed", "met")
    make_run(tmp_path, "unlisted", "not_met")
    write_manifest(tmp_path, [path.name])

    result = summarize_batch_reviews(tmp_path)

    assert result["batch_id"] == "test-batch"
    assert result["total_runs"] == 1
    assert result["reviewed_runs"] == 1
    assert result["criteria"]["causal_explanation"]["met_rate"] == 1.0


@pytest.mark.parametrize("overrides, message", [
    ({"case_id": "different_case"}, "Batch case"),
    ({"attempts": 2}, "attempt count"),
])
def test_batch_summary_rejects_inconsistent_manifest(tmp_path, overrides, message):
    path = make_run(tmp_path, "listed")
    write_manifest(tmp_path, [path.name], **overrides)

    with pytest.raises(ValueError, match=message):
        summarize_batch_reviews(tmp_path)


def test_batch_summary_rejects_directory_paths(tmp_path):
    write_manifest(tmp_path, ["../outside.json"])

    with pytest.raises(ValueError, match="JSON filenames"):
        summarize_batch_reviews(tmp_path)


def test_batch_summary_does_not_ignore_missing_reports(tmp_path):
    write_manifest(tmp_path, ["missing.json"])

    with pytest.raises(FileNotFoundError):
        summarize_batch_reviews(tmp_path)
