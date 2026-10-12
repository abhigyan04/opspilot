import json

import pytest

from evals.assessment import DiagnosisReview, save_review
from evals.review_summary import main, CRITERION_NAMES, summarize_reviews, summarize_batch_reviews, find_comparison_reports, summarize_comparison_reviews
from app.agent.settings import DiagnosisSettings


def make_run(tmp_path, run_id, verdict=None, case_id="checkout_regression", **report_fields):
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
            **report_fields
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


def write_comparison_report(directory, run_id="run", **overrides):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.json"
    path.write_text(
        json.dumps({
            "report_version": 2,
            "evaluation_mode": "diagnosis_replay",
            "status": "completed",
            **overrides,
        }),
        encoding="utf-8",
    )
    return path


def test_comparison_discovery_includes_failed_runs_and_skips_sidecars(tmp_path):
    first = write_comparison_report(
        tmp_path / "qwen3-4b" / "checkout_regression" / "seed-42",
        "first",
    )
    second = write_comparison_report(
        tmp_path / "qwen3-4b" / "sparse_evidence" / "seed-43",
        "second",
        status="failed",
    )

    first.with_suffix(".review.json").write_text("{}", encoding="utf-8")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "models.txt").write_text("model metadata", encoding="utf-8")

    assert find_comparison_reports(tmp_path) == sorted([first, second])


@pytest.mark.parametrize("overrides", [
    {"report_version": 1},
    {"evaluation_mode": "full_pipeline"},
    {"status": "running"},
])
def test_comparison_discovery_rejects_invalid_reports(tmp_path, overrides):
    write_comparison_report(tmp_path, **overrides)

    with pytest.raises(ValueError):
        find_comparison_reports(tmp_path)


def test_comparison_discovery_rejects_malformed_json(tmp_path):
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        find_comparison_reports(tmp_path)


def test_comparison_discovery_rejects_empty_directory(tmp_path):
    with pytest.raises(ValueError, match="No diagnosis replay reports"):
        find_comparison_reports(tmp_path)


def test_comparison_discovery_rejects_missing_directory(tmp_path):
    with pytest.raises(ValueError, match="directory must exist"):
        find_comparison_reports(tmp_path / "missing")


def make_comparison_run(
    directory, run_id, verdict=None, *, seed=42, **overrides
):
    directory.mkdir(parents=True, exist_ok=True)
    fields = {
        "evaluation_mode": "diagnosis_replay",
        "diagnosis_model": "qwen3:4b",
        "diagnosis_settings": DiagnosisSettings(seed=seed).model_dump(),
        "source": {
            "report_file": "source.json",
            "run_id": "source-run",
            "sha256": "a" * 64,
        },
        **overrides,
    }
    return make_run(directory, run_id, verdict, **fields)


def test_comparison_summary_combines_seeds_and_preserves_denominators(tmp_path):
    make_comparison_run(tmp_path / "seed-42", "first", "met")
    make_comparison_run(
        tmp_path / "seed-43", "second", "not_assessable", seed=43
    )
    make_comparison_run(tmp_path / "seed-44", "third", seed=44)

    result = summarize_comparison_reviews(tmp_path)

    assert result["total_runs"] == 3
    assert result["reviewed_runs"] == 2
    assert result["unreviewed_runs"] == 1
    assert len(result["groups"]) == 1

    group = result["groups"][0]
    assert group["seeds"] == [42, 43, 44]
    assert "seed" not in group["diagnosis_settings"]
    assert len(group["report_files"]) == 3
    assert group["criteria"]["causal_explanation"] == {
        "met": 1,
        "not_met": 0,
        "not_assessable": 1,
        "assessable": 1,
        "met_rate": 1.0,
    }


@pytest.mark.parametrize("overrides", [
    {"case_id": "sparse_evidence"},
    {"diagnosis_model": "qwen3:8b"},
    {"source": {
        "report_file": "different.json",
        "run_id": "different-source",
        "sha256": "b" * 64,
    }},
    {"diagnosis_settings": DiagnosisSettings(
        temperature=0.8
    ).model_dump()},
])
def test_comparison_summary_separates_different_inputs(tmp_path, overrides):
    make_comparison_run(tmp_path / "first", "first")
    make_comparison_run(tmp_path / "second", "second", **overrides)

    result = summarize_comparison_reviews(tmp_path)

    assert len(result["groups"]) == 2
    assert all(group["total_runs"] == 1 for group in result["groups"])


def test_comparison_summary_rejects_duplicates_across_groups(tmp_path):
    make_comparison_run(tmp_path / "first", "duplicate")
    make_comparison_run(
        tmp_path / "second", "duplicate", diagnosis_model="qwen3:8b"
    )

    with pytest.raises(ValueError, match="Duplicate"):
        summarize_comparison_reviews(tmp_path)


def test_comparison_summary_rejects_incomplete_settings(tmp_path):
    make_comparison_run(
        tmp_path, "incomplete", diagnosis_settings={"seed": 42}
    )

    with pytest.raises(ValueError, match="Explicit diagnosis settings"):
        summarize_comparison_reviews(tmp_path)


def test_comparison_summary_rejects_changed_reviewed_report(tmp_path):
    path = make_comparison_run(tmp_path, "changed", "met")
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="hash"):
        summarize_comparison_reviews(tmp_path)


def test_review_summary_cli_supports_comparison_directory(tmp_path, capsys):
    make_comparison_run(tmp_path / "seed-42", "first", "met")
    make_comparison_run(tmp_path / "seed-43", "second", seed=43)

    exit_code = main([str(tmp_path), "--comparison"])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["comparison_id"] == tmp_path.name
    assert result["total_runs"] == 2
    assert result["reviewed_runs"] == 1
    assert result["unreviewed_runs"] == 1
    assert len(result["groups"]) == 1


def test_review_summary_cli_preserves_batch_behavior(tmp_path, capsys):
    path = make_run(tmp_path, "listed", "met")
    write_manifest(tmp_path, [path.name])

    exit_code = main([str(tmp_path)])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["batch_id"] == "test-batch"
    assert result["total_runs"] == 1
    assert result["reviewed_runs"] == 1
    assert "groups" not in result


def test_review_summary_cli_reports_invalid_review(tmp_path, capsys):
    path = make_comparison_run(tmp_path, "changed", "met")
    path.write_bytes(path.read_bytes() + b"\n")

    exit_code = main([str(tmp_path), "--comparison"])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Review summary failed:" in output
    assert "hash" in output


def test_review_summary_cli_reports_missing_directory(tmp_path, capsys):
    exit_code = main([str(tmp_path / "missing"), "--comparison"])

    assert exit_code == 1
    assert "directory must exist" in capsys.readouterr().out
