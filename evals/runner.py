import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.agent.agent import generate_diagnosis, investigate
from evals.cases import CHECKOUT_REGRESSION, EvaluationCase
from evals.evaluator import evaluate_investigation


def run_case(case: EvaluationCase) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()

    # Only the incident goes to the investigating model.
    investigation = investigate(case.incident)
    investigation_seconds = perf_counter() - started

    diagnosis_started = perf_counter()
    diagnosis = generate_diagnosis(case.incident, investigation["steps"])
    diagnosis_seconds = perf_counter() - diagnosis_started

    return {
        "report_version": 1,
        "run_id": str(uuid4()),
        "started_at": started_at,
        "case_id": case.case_id,
        "incident": case.incident,
        "timing": {
            "investigation_seconds": investigation_seconds,
            "diagnosis_seconds": diagnosis_seconds,
            "total_seconds": perf_counter() - started,
        },
        "metrics": evaluate_investigation(case, investigation),
        "diagnosis_assessment": {
            "status": "not_scored",
            "reference_root_cause": case.reference_root_cause,
        },
        "investigation": investigation,
        "diagnosis": diagnosis.model_dump(mode="json"),
    }


def save_report(report: dict, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{report['run_id']}.json"

    # Refuse to overwrite an existing report.
    with destination.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")

    return destination


if __name__ == "__main__":
    report = run_case(CHECKOUT_REGRESSION)

    output_directory = (
        Path(__file__).resolve().parents[1] / "out" / "evals"
    )
    destination = save_report(report, output_directory)

    print(json.dumps({"report_path": str(destination),"metrics": report["metrics"],"timing": report["timing"],"diagnosis_assessment": report["diagnosis_assessment"]["status"]}, indent=2))
