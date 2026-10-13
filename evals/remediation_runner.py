from pathlib import Path
import argparse
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.agent.remediation import build_rollback_proposal
from app.agent.schemas import diagnosis_adapter
from evals.remediation import EXPECTED_ROLLBACKS, evaluate_rollback_proposal
from evals.replay import load_replay_source
from evals.runner import save_report
from evals.review_summary import find_comparison_reports
from app.agent import remediation as remediation_policy
from evals import remediation as remediation_evaluator


def evaluate_saved_remediation(report_path: Path, *, service: str) -> dict:
    if not isinstance(service, str) or not service.strip():
        raise ValueError("A nonblank service is required.")

    source = load_replay_source(report_path)
    report = source["report"]

    if report.get("evaluation_mode", "full_pipeline") not in {
        "full_pipeline",
        "diagnosis_replay",
    }:
        raise ValueError("Expected an investigation or diagnosis replay report.")

    if report.get("status") != "completed" or report.get("diagnosis") is None:
        raise ValueError("A completed report with a diagnosis is required.")

    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("A source run ID is required.")

    case_id = report.get("case_id")
    if not isinstance(case_id, str) or case_id not in EXPECTED_ROLLBACKS:
        raise ValueError(f"No remediation expectation for case: {case_id}")

    diagnosis = diagnosis_adapter.validate_python(report["diagnosis"])

    proposal = build_rollback_proposal(
        diagnosis,
        service,
        report["investigation"]["steps"],
    )
    assessment = evaluate_rollback_proposal(case_id, proposal)

    return {
        "source_report": source["source_report"],
        "source_run_id": run_id,
        "source_sha256": source["source_sha256"],
        "service": service,
        "diagnosis_model": report.get("diagnosis_model"),
        "diagnosis_settings": report.get("diagnosis_settings"),
        "diagnosis_status": diagnosis.status,
        "proposal": proposal.model_dump() if proposal is not None else None,
        **assessment,
    }


def evaluate_remediation_reports(report_paths: list[Path], *, service: str) -> dict:
    if not report_paths:
        raise ValueError("At least one source report is required.")

    started_at = datetime.now(timezone.utc).isoformat()
    results = []
    seen_run_ids = set()
    by_case = {}

    for path in report_paths:
        result = evaluate_saved_remediation(path, service=service)

        if result["source_run_id"] in seen_run_ids:
            raise ValueError("Duplicate source run ID.")
        seen_run_ids.add(result["source_run_id"])

        result["source_path"] = str(path.resolve())
        results.append(result)

        counts = by_case.setdefault(
            result["case_id"], {"attempts": 0, "matches": 0}
        )
        counts["attempts"] += 1
        counts["matches"] += int(result["matches_expectation"])

    code_files = {
        "proposal_policy": Path(remediation_policy.__file__),
        "evaluator": Path(remediation_evaluator.__file__),
        "runner": Path(__file__),
    }

    return {
        "report_version": 1,
        "evaluation_mode": "remediation_proposal_evaluation",
        "run_id": str(uuid4()),
        "started_at": started_at,
        "service": service,
        "code_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in code_files.items()
        },
        "total_attempts": len(results),
        "matching_proposals": sum(
            result["matches_expectation"] for result in results
        ),
        "by_case": by_case,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate rollback candidates from saved diagnoses."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="A saved report or a comparison directory containing replays.",
    )
    parser.add_argument("--service", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "out" / "remediation",
    )
    args = parser.parse_args(argv)

    try:
        if args.source.is_dir():
            if args.output_dir.resolve().is_relative_to(args.source.resolve()):
                raise ValueError(
                    "Output directory must be outside the comparison directory."
                )
            paths = find_comparison_reports(args.source)
        else:
            paths = [args.source]

        report = evaluate_remediation_reports(paths, service=args.service)
        destination = save_report(report, args.output_dir)
    except (ValueError, OSError, KeyError) as error:
        print(f"Remediation evaluation failed: {error}")
        return 1

    print(json.dumps({
        "report_path": str(destination.resolve()),
        "run_id": report["run_id"],
        "total_attempts": report["total_attempts"],
        "matching_proposals": report["matching_proposals"],
        "by_case": report["by_case"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
