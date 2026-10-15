from copy import deepcopy
from datetime import datetime


def build_evidence_timeline(steps: list[dict]) -> list[dict]:
    events = []

    for step in steps:
        result = step["result"]
        records = result if isinstance(result, list) else [result]

        for record in records:
            if not isinstance(record, dict):
                continue

            timestamp = record.get("timestamp")
            if not isinstance(timestamp, str):
                continue

            try:
                instant = datetime.fromisoformat(timestamp)
            except ValueError:
                continue

            if instant.utcoffset() is None:
                continue

            events.append((
                instant,
                {
                    "evidence_id": step["evidence_id"],
                    "tool": step["decision"]["tool"],
                    "record": deepcopy(record),
                },
            ))

    events.sort(key=lambda event: event[0])
    return [event for _, event in events]


def build_deployment_timing(steps: list[dict]) -> list[dict]:
    timeline = build_evidence_timeline(steps)
    comparisons = []

    for deployment in timeline:
        if deployment["tool"] != "get_deployments":
            continue

        service = deployment["record"].get("service")
        if not isinstance(service, str) or not service.strip():
            continue

        earliest_error = next(
            (
                event
                for event in timeline
                if event["tool"] == "search_logs"
                and event["record"].get("service") == service
                and event["record"].get("level") in {"ERROR", "CRITICAL"}
            ),
            None,
        )
        if earliest_error is None:
            continue

        error_time = datetime.fromisoformat(
            earliest_error["record"]["timestamp"]
        )
        deployment_time = datetime.fromisoformat(
            deployment["record"]["timestamp"]
        )

        if error_time < deployment_time:
            relation = "before"
        elif error_time > deployment_time:
            relation = "after"
        else:
            relation = "same_time"

        comparisons.append({
            "service": service,
            "earliest_observed_error": earliest_error,
            "deployment": deployment,
            "error_relative_to_deployment": relation,
        })

    return comparisons
