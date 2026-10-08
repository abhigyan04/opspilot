import hashlib
import json
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import argparse

from evals.runner import save_report
from app.agent.agent import generate_diagnosis


def load_replay_source(report_path: Path) -> dict:
    original_bytes = report_path.read_bytes()
    report = json.loads(original_bytes)

    if not isinstance(report, dict) or report.get("report_version") != 2:
        raise ValueError("Replay requires a version 2 run report.")

    investigation = report.get("investigation")
    if not isinstance(investigation, dict):
        raise ValueError("Replay requires a saved investigation.")

    if investigation.get("status") not in {"finished", "step_limit"}:
        raise ValueError("Replay requires a completed investigation.")

    if not isinstance(investigation.get("steps"), list):
        raise ValueError("Replay requires an investigation steps list.")

    incident = report.get("incident")
    if not isinstance(incident, str) or not incident.strip():
        raise ValueError("Replay requires a nonblank incident.")

    return {
        "source_report": report_path.name,
        "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "report": report,
    }


def replay_diagnosis(report_path: Path) -> dict:
    started = perf_counter()
    source = load_replay_source(report_path)
    original = source["report"]

    assessment = {
        "status": "not_scored",
    }
    original_assessment = original.get("diagnosis_assessment") or {}
    if "reference_root_cause" in original_assessment:
        assessment["reference_root_cause"] = (
            original_assessment["reference_root_cause"]
        )

    report = {
        "report_version": 2,
        "evaluation_mode": "diagnosis_replay",
        "run_id": str(uuid4()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "case_id": original["case_id"],
        "incident": original["incident"],
        "source": {
            "report_file": source["source_report"],
            "run_id": original["run_id"],
            "sha256": source["source_sha256"],
        },
        "status": "running",
        "error": None,
        "timing": {
            "investigation_seconds": None,
            "scoring_seconds": None,
            "diagnosis_seconds": None,
            "total_seconds": None,
        },
        "metrics": None,
        "diagnosis_assessment": assessment,
        "investigation": deepcopy(original["investigation"]),
        "diagnosis": None,
    }

    diagnosis_started = perf_counter()
    try:
        diagnosis = generate_diagnosis(
            report["incident"],
            deepcopy(report["investigation"]["steps"]),
        )
        report["diagnosis"] = diagnosis.model_dump(mode="json")
        report["status"] = "completed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {
            "stage": "diagnosis",
            "type": type(error).__name__,
            "message": str(error),
        }

    report["timing"]["diagnosis_seconds"] = (
        perf_counter() - diagnosis_started
    )
    report["timing"]["total_seconds"] = perf_counter() - started
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay diagnosis using a saved investigation."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "out" / "replays",
    )
    args = parser.parse_args(argv)

    try:
        report = replay_diagnosis(args.report)
        destination = save_report(report, args.output_dir)
    except (OSError, ValueError, KeyError) as error:
        print(f"Replay failed: {error}")
        return 1

    print(json.dumps({
        "report_path": str(destination),
        "run_id": report["run_id"],
        "evaluation_mode": report["evaluation_mode"],
        "status": report["status"],
        "source": report["source"],
        "timing": report["timing"],
        "error": report["error"],
    }, indent=2))

    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
