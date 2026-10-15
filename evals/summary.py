from collections import Counter
from statistics import mean


def summarize_usage(reports: list[dict]) -> dict:
    recorded = [
        report["usage"]["totals"]
        for report in reports
        if report.get("usage") is not None
    ]

    result = {
        "reports_with_usage": len(recorded),
        "reports_without_usage": len(reports) - len(recorded),
        "recorded_model_attempts": sum(
            totals["attempts"] for totals in recorded
        ),
    }

    for direction in ("input", "output"):
        field = f"{direction}_tokens"
        known_field = f"known_{direction}_tokens"
        counted_field = f"{direction}_counted_calls"

        result[counted_field] = sum(
            totals[counted_field] for totals in recorded
        )
        result[known_field] = sum(
            totals[known_field] for totals in recorded
        )

        complete = (
            len(recorded) == len(reports)
            and all(totals[field] is not None for totals in recorded)
        )
        result[field] = (
            sum(totals[field] for totals in recorded)
            if complete
            else None
        )

    return result


def summarize_reports(reports: list[dict]) -> dict:
    if not reports:
        raise ValueError("At least one report is required.")

    if any(report["report_version"] != 2 for report in reports):
        raise ValueError("Summary requires version 2 reports.")
    
    if any(
        report.get("evaluation_mode", "full_pipeline") != "full_pipeline"
        for report in reports
    ):
        raise ValueError(
            "Pipeline summaries cannot include diagnosis replays."
        )

    case_ids = {report["case_id"] for report in reports}
    if len(case_ids) != 1:
        raise ValueError("Summarize one evaluation case at a time.")

    if any(
        report["status"] not in {"completed", "failed"}
        for report in reports
    ):
        raise ValueError("Summary requires finished reports.")

    completed = sum(
        report["status"] == "completed"
        for report in reports
    )
    failed = len(reports) - completed

    coverage_values = [
        report["metrics"]["required_tool_coverage"]
        for report in reports
        if report["metrics"] is not None
    ]

    failure_stages = Counter(
        report["error"]["stage"]
        for report in reports
        if report["status"] == "failed"
    )

    return {
        "case_id": reports[0]["case_id"],
        "attempts": len(reports),
        "completed": completed,
        "failed": failed,
        "pipeline_completion_rate": completed / len(reports),
        "mean_total_seconds": mean(
            report["timing"]["total_seconds"]
            for report in reports
        ),
        "coverage_observations": len(coverage_values),
        "mean_required_tool_coverage": (
            mean(coverage_values) if coverage_values else None
        ),
        "failure_stages": dict(failure_stages),
        "diagnosis_accuracy": None,
        "usage": summarize_usage(reports)
    }
