import json
import argparse

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.agent.agent import generate_diagnosis, investigate
from evals.cases import CHECKOUT_REGRESSION, EvaluationCase
from evals.evaluator import evaluate_investigation
from evals.summary import summarize_reports


def run_case(case: EvaluationCase) -> dict:
    started = perf_counter()

    report = {
        "report_version": 2,
        "run_id": str(uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "case_id": case.case_id,
        "incident": case.incident,
        "status": "running",
        "error": None,
        "timing": {
            "investigation_seconds": None,
            "scoring_seconds": None,
            "diagnosis_seconds": None,
            "total_seconds": None,
        },
        "metrics": None,
        "diagnosis_assessment": {
            "status": "not_scored",
            "reference_root_cause": case.reference_root_cause,
        },
        "investigation": None,
        "diagnosis": None,
    }

    stage = "investigation"
    stage_started = perf_counter()

    try:
        report["investigation"] = investigate(case.incident)
        report["timing"]["investigation_seconds"] = (
            perf_counter() - stage_started
        )

        stage = "scoring"
        stage_started = perf_counter()
        report["metrics"] = evaluate_investigation(
            case, report["investigation"]
        )
        report["timing"]["scoring_seconds"] = (
            perf_counter() - stage_started
        )

        stage = "diagnosis"
        stage_started = perf_counter()
        diagnosis = generate_diagnosis(
            case.incident,
            report["investigation"]["steps"],
        )
        report["diagnosis"] = diagnosis.model_dump(mode="json")
        report["timing"]["diagnosis_seconds"] = (
            perf_counter() - stage_started
        )

        report["status"] = "completed"

    except Exception as error:
        report["timing"][f"{stage}_seconds"] = (
            perf_counter() - stage_started
        )
        report["status"] = "failed"
        report["error"] = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error),
        }

    report["timing"]["total_seconds"] = perf_counter() - started
    return report


def save_report(report: dict, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{report['run_id']}.json"

    # Refuse to overwrite an existing report.
    with destination.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")

    return destination


def run_batch(case: EvaluationCase, runs: int, output_directory: Path) -> dict:
    if runs < 1:
        raise ValueError("runs must be at least 1")

    batch_id = str(uuid4())
    batch_directory = output_directory / batch_id
    reports = []
    report_files = []

    for _ in range(runs):
        report = run_case(case)

        # Persist this attempt before starting another.
        destination = save_report(report, batch_directory)
        reports.append(report)
        report_files.append(destination.name)

    batch = {
        "run_id": "summary",
        "batch_id": batch_id,
        "report_files": report_files,
        "summary": summarize_reports(reports),
    }
    destination = save_report(batch, batch_directory)

    return {
        "summary_path": str(destination),
        **batch,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate OpsPilot on the checkout regression."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of sequential evaluation attempts (default: 1).",
    )
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    output_directory = (
        Path(__file__).resolve().parents[1] / "out" / "evals"
    )
    batch = run_batch(
        CHECKOUT_REGRESSION,
        args.runs,
        output_directory,
    )

    print(json.dumps(batch, indent=2))

    raise SystemExit(1 if batch["summary"]["failed"] else 0)
