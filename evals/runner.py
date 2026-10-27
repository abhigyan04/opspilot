import json
import argparse

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import asyncio

from app.agent.agent import investigate_async
from app.mcp_server.client import connect_local_tools
from app.tools.data import SCENARIOS_ROOT
from app.mcp_server.server import SUPPORTED_SCENARIOS
from app.agent.agent import (
    DEFAULT_DIAGNOSIS_MODEL, 
    generate_diagnosis, 
    investigate
)
from app.agent.settings import DiagnosisSettings, RuntimeSettings
from app.agent.usage import UsageCollector
from evals.cases import CASES, EvaluationCase
from evals.evaluator import evaluate_investigation
from evals.summary import summarize_reports


async def investigate_over_mcp(incident: str, *, scenario: str, usage: UsageCollector):
    async with connect_local_tools(scenario=scenario) as executor:
        return await investigate_async(
            incident,
            usage=usage,
            tool_executor=executor.execute,
        )


def run_case(case: EvaluationCase, *, diagnosis_model: str | None = None, diagnosis_settings: DiagnosisSettings | None = None, tool_backend: str = "direct") -> dict:
    diagnosis_model = RuntimeSettings.from_env().diagnosis_model if diagnosis_model is None else diagnosis_model
    if tool_backend not in {"direct", "mcp"}:
        raise ValueError("tool_backend must be 'direct' or 'mcp'")

    if tool_backend == "mcp":
        if case.case_id not in SUPPORTED_SCENARIOS:
            raise ValueError(f"Unsupported MCP scenario: {case.case_id}")

        expected_dir = SCENARIOS_ROOT / case.case_id
        if case.scenario_dir.resolve() != expected_dir.resolve():
            raise ValueError(
                "MCP requires the standard fixture directory for the selected case."
            )

    if not isinstance(diagnosis_model, str) or not diagnosis_model.strip():
        raise ValueError("A nonblank diagnosis model is required.")
    
    settings = (
        diagnosis_settings
        if diagnosis_settings is not None
        else DiagnosisSettings()
    )
    started = perf_counter()
    usage = UsageCollector()

    report = {
        "report_version": 2,
        "evaluation_mode": "full_pipeline",
        "diagnosis_model": diagnosis_model,
        "diagnosis_settings": settings.model_dump(mode="json"),
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
        "tool_backend": tool_backend
    }

    stage = "investigation"
    stage_started = perf_counter()

    try:
        if tool_backend == "direct":
            report["investigation"] = investigate(
                case.incident,
                data_dir=case.scenario_dir,
                usage=usage,
            )
        else:
            report["investigation"] = asyncio.run(
                investigate_over_mcp(case.incident, scenario=case.case_id, usage=usage)
            )
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
            model=diagnosis_model,
            settings=settings,
            usage=usage
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

    report["usage"] = usage.snapshot()
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


def run_batch(case: EvaluationCase, runs: int, output_directory: Path, *, diagnosis_model: str | None = None, diagnosis_settings: DiagnosisSettings | None = None, tool_backend: str = "direct") -> dict:
    diagnosis_model = RuntimeSettings.from_env().diagnosis_model if diagnosis_model is None else diagnosis_model
    if runs < 1:
        raise ValueError("runs must be at least 1")

    batch_id = str(uuid4())
    batch_directory = output_directory / batch_id
    reports = []
    report_files = []

    for _ in range(runs):
        report = run_case(case, diagnosis_model=diagnosis_model, diagnosis_settings=diagnosis_settings, tool_backend=tool_backend)

        # Persist this attempt before starting another.
        destination = save_report(report, batch_directory)
        reports.append(report)
        report_files.append(destination.name)

    batch = {
        "run_id": "summary",
        "batch_id": batch_id,
        "report_files": report_files,
        "summary": summarize_reports(reports),
        "tool_backend": tool_backend
    }
    destination = save_report(batch, batch_directory)

    return {
        "summary_path": str(destination),
        **batch,
    }


def parse_arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Evaluate OpsPilot on a synthetic incident."
    )
    parser.add_argument(
        "--case",
        choices=sorted(CASES),
        default="checkout_regression",
        help="Incident scenario to evaluate.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of sequential evaluation attempts (default: 1).",
    )
    
    parser.add_argument(
        "--model",
        default=RuntimeSettings.from_env().diagnosis_model,
        help="Ollama diagnosis model tag (default: %(default)s).",
    )

    defaults = DiagnosisSettings()
    parser.add_argument("--num-ctx", type=int, default=defaults.num_ctx)
    parser.add_argument("--num-predict", type=int, default=defaults.num_predict, help="Maximum diagnosis generation tokens (default: %(default)s).")
    parser.add_argument(
        "--temperature", type=float, default=defaults.temperature
    )
    parser.add_argument("--top-p", type=float, default=defaults.top_p)
    parser.add_argument("--top-k", type=int, default=defaults.top_k)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument(
        "--think",
        action=argparse.BooleanOptionalAction,
        default=defaults.think,
        help="Enable thinking; use --no-think to disable it.",
    )
    parser.add_argument(
        "--tool-backend",
        choices=["direct", "mcp"],
        default="direct",
        help="Investigation tool backend (default: %(default)s).",
    )

    args = parser.parse_args(argv)

    if args.runs < 1:
        parser.error("--runs must be at least 1")
    
    if not args.model.strip():
        parser.error("--model must not be blank")

    if args.tool_backend == "mcp" and args.case not in SUPPORTED_SCENARIOS:
        parser.error(f"Unsupported MCP scenario: {args.case}")

    try:
        args.diagnosis_settings = DiagnosisSettings(
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            temperature=args.temperature,
            top_p=args.top_p,
            top_k=args.top_k,
            seed=args.seed,
            think=args.think,
        )
    except ValueError as error:
        parser.error(str(error))

    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)

    output_directory = (
        Path(__file__).resolve().parents[1] / "out" / "evals"
    )
    batch = run_batch(
        CASES[args.case],
        args.runs,
        output_directory,
        diagnosis_model=args.model,
        diagnosis_settings=args.diagnosis_settings,
        tool_backend=args.tool_backend
    )

    print(json.dumps(batch, indent=2))
    return 1 if batch["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
