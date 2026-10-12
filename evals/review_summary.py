import json
import argparse
from pathlib import Path

from evals.assessment import load_review
from app.agent.settings import DiagnosisSettings


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


def find_comparison_reports(comparison_directory: Path) -> list[Path]:
    if not comparison_directory.is_dir():
        raise ValueError("Comparison directory must exist.")

    report_paths = []

    for path in sorted(comparison_directory.rglob("*.json")):
        if path.name == "summary.json" or path.name.endswith(".review.json"):
            continue

        report = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(report, dict):
            raise ValueError(f"Expected a report object: {path}")

        if (
            report.get("report_version") != 2
            or report.get("evaluation_mode") != "diagnosis_replay"
        ):
            raise ValueError(
                f"Expected a version 2 diagnosis replay report: {path}"
            )

        if report.get("status") not in {"completed", "failed"}:
            raise ValueError(f"Replay report is not finished: {path}")

        report_paths.append(path)

    if not report_paths:
        raise ValueError("No diagnosis replay reports found.")

    return report_paths


def summarize_comparison_reviews(comparison_directory: Path) -> dict:
    report_paths = find_comparison_reports(comparison_directory)
    groups = {}
    seen_run_ids = set()

    for path in report_paths:
        report = json.loads(path.read_text(encoding="utf-8"))

        for field in ("run_id", "case_id", "diagnosis_model"):
            value = report.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing or invalid {field}: {path}")

        if report["run_id"] in seen_run_ids:
            raise ValueError("Duplicate run ID.")
        seen_run_ids.add(report["run_id"])

        source = report.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"Missing source provenance: {path}")

        for field in ("report_file", "run_id", "sha256"):
            value = source.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing source {field}: {path}")

        raw_settings = report.get("diagnosis_settings")
        required_fields = set(DiagnosisSettings.model_fields)
        if (
            not isinstance(raw_settings, dict)
            or not required_fields.issubset(raw_settings)
        ):
            raise ValueError(f"Explicit diagnosis settings required: {path}")

        settings = DiagnosisSettings.model_validate(raw_settings)
        shared_settings = settings.model_dump(exclude={"seed"})

        metadata = {
            "case_id": report["case_id"],
            "diagnosis_model": report["diagnosis_model"],
            "source": source,
            "diagnosis_settings": shared_settings,
        }
        key = json.dumps(metadata, sort_keys=True)

        if key not in groups:
            groups[key] = {
                "metadata": metadata,
                "paths": [],
                "seeds": [],
            }

        groups[key]["paths"].append(path)
        groups[key]["seeds"].append(settings.seed)

    summaries = []
    for key in sorted(groups):
        group = groups[key]
        summary = summarize_reviews(group["paths"])
        summaries.append({
            **group["metadata"],
            **summary,
            "seeds": sorted(group["seeds"]),
            "report_files": [
                path.relative_to(comparison_directory).as_posix()
                for path in group["paths"]
            ],
        })

    reviewed = sum(group["reviewed_runs"] for group in summaries)

    return {
        "comparison_id": comparison_directory.name,
        "total_runs": len(report_paths),
        "reviewed_runs": reviewed,
        "unreviewed_runs": len(report_paths) - reviewed,
        "groups": summaries,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize verified human diagnosis reviews."
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--comparison",
        action="store_true",
        help="Discover and group diagnosis replays in a comparison directory.",
    )
    args = parser.parse_args(argv)

    try:
        if args.comparison:
            result = summarize_comparison_reviews(args.directory)
        else:
            result = summarize_batch_reviews(args.directory)
    except (ValueError, OSError, KeyError) as error:
        print(f"Review summary failed: {error}")
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
