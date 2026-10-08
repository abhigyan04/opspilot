from collections import Counter
from statistics import mean


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
    }
