import hashlib
import json
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4
import argparse
from psycopg import Connection
import os
import psycopg

from evals.runner import save_report
from app.agent.agent import generate_diagnosis, DEFAULT_DIAGNOSIS_MODEL
from app.agent.settings import DiagnosisSettings
from app.agent.usage import UsageCollector
from app.retrieval.context import build_reference_context
from app.retrieval.search import SearchHit
from app.retrieval.pg_retrieve import retrieve_postgres
from app.retrieval.query import QUERY_VERSION, build_retrieval_query


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


def replay_diagnosis(report_path: Path, *, model: str = DEFAULT_DIAGNOSIS_MODEL, settings: DiagnosisSettings | None = None, reference_hits: list[SearchHit] | None = None, retrieval_connection: Connection | None = None, retrieval_top_k: int = 3) -> dict:
    if retrieval_connection is not None:
        if reference_hits is not None:
            raise ValueError(
                "Choose supplied reference hits or PostgreSQL retrieval, not both."
            )
        if type(retrieval_top_k) is not int or retrieval_top_k < 1:
            raise ValueError("retrieval_top_k must be a positive integer.")
    
    started = perf_counter()
    effective_settings = (
        DiagnosisSettings() if settings is None else settings
    )
    source = load_replay_source(report_path)
    original = source["report"]
    usage = UsageCollector()
    
    supplied_hits = deepcopy(reference_hits or [])
    reference_context = build_reference_context(supplied_hits)

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
        "diagnosis_model": model,
        "diagnosis_settings": effective_settings.model_dump(mode="json"),
        "reference_context": reference_context,
        "retrieval": None,
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
            "retrieval_seconds": None
        },
        "metrics": None,
        "diagnosis_assessment": assessment,
        "investigation": deepcopy(original["investigation"]),
        "diagnosis": None,
    }

    stage = "retrieval" if retrieval_connection is not None else "diagnosis"
    diagnosis_started = None

    try:
        if retrieval_connection is not None:
            retrieval_query = build_retrieval_query(
                            report["incident"],
                            report["investigation"]["steps"]
                        )
            
            report["retrieval"] = {
                "backend": "postgres",
                "query": retrieval_query,
                "query_version": QUERY_VERSION,
                "query_strategy": "errors_only_with_incident_fallback",
                "top_k": retrieval_top_k,
                "index_id": None,
                "embedding_identity": None,
                "results": None,
            }

            retrieval_started = perf_counter()
            try:
                retrieved = retrieve_postgres(
                    retrieval_query,
                    retrieval_connection,
                    top_k=retrieval_top_k,
                )
                supplied_hits = deepcopy(retrieved.hits)
                report["reference_context"] = build_reference_context(
                    supplied_hits
                )
                report["retrieval"].update({
                    "index_id": retrieved.index_id,
                    "embedding_identity": deepcopy(
                        retrieved.embedding_identity
                    ),
                    "results": [
                        {
                            "chunk_id": hit.chunk.chunk_id,
                            "score": hit.score,
                        }
                        for hit in supplied_hits
                    ],
                })
            finally:
                report["timing"]["retrieval_seconds"] = (
                    perf_counter() - retrieval_started
                )

        diagnosis_arguments = {}
        if supplied_hits:
            diagnosis_arguments["reference_hits"] = supplied_hits

        stage = "diagnosis"
        diagnosis_started = perf_counter()

        diagnosis = generate_diagnosis(
            report["incident"],
            deepcopy(report["investigation"]["steps"]),
            model=model,
            settings=effective_settings,
            usage=usage,
            **diagnosis_arguments,
        )
        report["diagnosis"] = diagnosis.model_dump(mode="json")
        report["status"] = "completed"

    except Exception as error:
        report["status"] = "failed"
        report["error"] = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error),
        }

    report["usage"] = usage.snapshot()

    if diagnosis_started is not None:
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
    parser.add_argument(
        "--model",
        default=DEFAULT_DIAGNOSIS_MODEL,
        help=f"Ollama diagnosis model tag (default: %(default)s).",
    )

    defaults = DiagnosisSettings()

    parser.add_argument("--num-ctx", type=int, default=defaults.num_ctx)
    parser.add_argument("--temperature", type=float, default=defaults.temperature)
    parser.add_argument("--top-p", type=float, default=defaults.top_p)
    parser.add_argument("--top-k", type=int, default=defaults.top_k)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--think", action=argparse.BooleanOptionalAction,
                        default=defaults.think,
                        help="Enable thinking; use --no-think to disable it.")
    parser.add_argument(
        "--with-references",
        action="store_true",
        help="Retrieve references from PostgreSQL before diagnosis.",
    )
    parser.add_argument(
        "--retrieval-top-k",
        type=int,
        default=3,
        help="Number of reference passages to retrieve (default: 3).",
    )

    args = parser.parse_args(argv)
    
    if args.retrieval_top_k < 1:
        parser.error("--retrieval-top-k must be positive.")

    database_url = None
    if args.with_references:
        database_url = os.environ.get("OPSPILOT_DATABASE_URL")
        if not database_url or not database_url.strip():
            parser.error(
                "--with-references requires OPSPILOT_DATABASE_URL."
            )

    try:
        settings = DiagnosisSettings(
            num_ctx=args.num_ctx,
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            seed=args.seed,
            think=args.think,
        )
    except ValueError as error:
        parser.error(str(error))

    try:
        if args.with_references:
            with psycopg.connect(
                database_url,
                autocommit=True,
                connect_timeout=5,
            ) as connection:
                report = replay_diagnosis(
                    args.report,
                    model=args.model,
                    settings=settings,
                    retrieval_connection=connection,
                    retrieval_top_k=args.retrieval_top_k,
                )
        else:
            report = replay_diagnosis(
                args.report,
                model=args.model,
                settings=settings,
            )

        destination = save_report(report, args.output_dir)

    except psycopg.Error:
        print(
            "Replay failed: PostgreSQL connection or database operation failed. "
            "Check OPSPILOT_DATABASE_URL and database availability."
        )
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(f"Replay failed: {error}")
        return 1

    print(json.dumps({
        "report_path": str(destination),
        "run_id": report["run_id"],
        "evaluation_mode": report["evaluation_mode"],
        "diagnosis_model": report["diagnosis_model"],
        "diagnosis_settings": report["diagnosis_settings"],
        "status": report["status"],
        "source": report["source"],
        "timing": report["timing"],
        "error": report["error"],
        "usage": report["usage"]
    }, indent=2))

    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
