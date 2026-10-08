import json
import argparse
from pathlib import Path

from evals.assessment import load_review


CRITERION_NAMES = (
    "causal_explanation",
    "deployment_reasoning",
    "evidence_grounding",
    "uncertainty_handling",
)


def summarize_reviews(report_paths: list[Path]) -> dict:
    if not report_paths:
        raise ValueError("At least one report is required.")

    counts = {
        name: {"met": 0, "not_met": 0, "not_assessable": 0}
        for name in CRITERION_NAMES
    }
    seen_run_ids = set()
    case_id = None
    reviewed = 0

    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))

        if report.get("report_version") != 2:
            raise ValueError("Summary requires version 2 run reports.")

        if report["run_id"] in seen_run_ids:
            raise ValueError("Duplicate run ID.")
        seen_run_ids.add(report["run_id"])

        if case_id is None:
            case_id = report["case_id"]
        elif report["case_id"] != case_id:
            raise ValueError("Summarize one evaluation case at a time.")

        review = load_review(report_path)
        if review is None:
            continue

        reviewed += 1
        for name in CRITERION_NAMES:
            verdict = getattr(review, name).verdict
            counts[name][verdict] += 1

    criteria = {}
    for name, verdict_counts in counts.items():
        assessable = verdict_counts["met"] + verdict_counts["not_met"]
        criteria[name] = {
            **verdict_counts,
            "assessable": assessable,
            "met_rate": (
                verdict_counts["met"] / assessable
                if assessable else None
            ),
        }

    return {
        "case_id": case_id,
        "total_runs": len(report_paths),
        "reviewed_runs": reviewed,
        "unreviewed_runs": len(report_paths) - reviewed,
        "criteria": criteria,
    }


def summarize_batch_reviews(batch_directory: Path) -> dict:
    manifest = json.loads(
        (batch_directory / "summary.json").read_text(encoding="utf-8")
    )
    filenames = manifest["report_files"]

    if not isinstance(filenames, list):
        raise ValueError("report_files must be a list.")

    report_paths = []
    for filename in filenames:
        if (
            not isinstance(filename, str)
            or "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
            or not filename.endswith(".json")
        ):
            raise ValueError("Report entries must be JSON filenames.")

        report_paths.append(batch_directory / filename)

    result = summarize_reviews(report_paths)

    if result["case_id"] != manifest["summary"]["case_id"]:
        raise ValueError("Batch case does not match its reports.")

    if result["total_runs"] != manifest["summary"]["attempts"]:
        raise ValueError("Batch attempt count does not match its reports.")

    return {
        "batch_id": manifest["batch_id"],
        **result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Summarize verified human reviews for an evaluation batch."
    )
    parser.add_argument("batch_directory", type=Path)
    args = parser.parse_args()

    try:
        result = summarize_batch_reviews(args.batch_directory)
    except (ValueError, OSError, KeyError) as error:
        print(f"Review summary failed: {error}")
        raise SystemExit(1)

    print(json.dumps(result, indent=2))
