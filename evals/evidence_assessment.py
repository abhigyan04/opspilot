import json

from evals.cases import CASES
from evals.tool_assessment import EXPECTED_ARGUMENTS


FIXTURE_FILES = {
    "search_logs": "log.json",
    "query_metrics": "metrics.json",
    "get_deployments": "deployments.json",
    "get_commit": "commits.json",
}


def expected_results(case_id: str) -> dict:
    if case_id not in CASES:
        raise ValueError(f"No evidence expectations for case: {case_id}")

    case = CASES[case_id]
    expected = {}

    for tool, arguments in EXPECTED_ARGUMENTS[case_id].items():
        path = case.scenario_dir / FIXTURE_FILES[tool]
        records = json.loads(path.read_text(encoding="utf-8"))

        if tool == "get_commit":
            matches = [
                record for record in records
                if record["hash"] == arguments["commit_hash"]
            ]
            if len(matches) != 1:
                raise ValueError("Expected exactly one matching commit fixture.")
            expected[tool] = matches[0]
        else:
            matches = [
                record for record in records
                if record.get("service") == arguments["service"]
            ]
            if tool == "search_logs":
                matches = [
                    record for record in matches
                    if record.get("level") == arguments["level"]
                ]
            elif tool == "query_metrics":
                matches = [
                    record for record in matches
                    if record.get("metric") == arguments["metric_name"]
                ]
            expected[tool] = matches

    return expected


def _normalized(value):
    if isinstance(value, list):
        return sorted(
            json.dumps(item, sort_keys=True)
            for item in value
        )
    return json.dumps(value, sort_keys=True)


def evaluate_evidence_content(case_id: str, steps: list[dict]) -> dict:
    expected = expected_results(case_id)
    assessments = []

    for tool, expected_result in expected.items():
        calls = [
            step for step in steps
            if step["decision"]["tool"] == tool
        ]
        recorded = [step for step in calls if "result" in step]

        matched = any(
            _normalized(step["result"]) == _normalized(expected_result)
            for step in recorded
        )

        if matched:
            outcome = "matched"
        elif not calls:
            outcome = "not_called"
        elif not recorded:
            outcome = "result_not_recorded"
        else:
            outcome = "result_mismatch"

        assessments.append({
            "tool": tool,
            "expects_empty": expected_result == [],
            "outcome": outcome,
        })

    nonempty = [
        item for item in assessments if not item["expects_empty"]
    ]
    empty = [
        item for item in assessments if item["expects_empty"]
    ]
    captured = sum(item["outcome"] == "matched" for item in nonempty)

    return {
        "case_id": case_id,
        "required_nonempty_results": len(nonempty),
        "captured_nonempty_results": captured,
        "nonempty_result_coverage": (
            captured / len(nonempty) if nonempty else None
        ),
        "expected_empty_lookups": len(empty),
        "matched_empty_lookups": sum(
            item["outcome"] == "matched" for item in empty
        ),
        "assessments": assessments,
    }
