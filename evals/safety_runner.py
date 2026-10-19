import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.agent import remediation, schemas, verification
from evals import safety
from evals.runner import save_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate in-memory approval, execution, and recovery controls."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "out" / "safety",
    )
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    code_files = {
        "remediation": Path(remediation.__file__),
        "verification": Path(verification.__file__),
        "schemas": Path(schemas.__file__),
        "evaluator": Path(safety.__file__),
        "runner": Path(__file__),
    }

    report = {
        "report_version": 1,
        "run_id": str(uuid4()),
        "started_at": started_at,
        "code_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in code_files.items()
        },
        **safety.evaluate_simulation_controls(),
    }
    report["status"] = (
        "passed"
        if report["passed_checks"] == report["total_checks"]
        else "failed"
    )

    destination = save_report(report, args.output_dir)

    print(json.dumps({
        "report_path": str(destination.resolve()),
        "run_id": report["run_id"],
        "status": report["status"],
        "total_checks": report["total_checks"],
        "passed_checks": report["passed_checks"],
    }, indent=2))

    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
