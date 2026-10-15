EXPECTED_ARGUMENTS = {
    "checkout_regression": {
        "search_logs": {
            "service": "checkout-service",
            "level": "ERROR",
        },
        "query_metrics": {
            "service": "checkout-service",
            "metric_name": "error_rate",
        },
        "get_deployments": {"service": "checkout-service"},
        "get_commit": {"commit_hash": "a1b2c3d4e5f6g7h8i9j0"},
    },
    "payment_provider_outage": {
        "search_logs": {
            "service": "checkout-service",
            "level": "ERROR",
        },
        "query_metrics": {
            "service": "checkout-service",
            "metric_name": "error_rate",
        },
        "get_deployments": {"service": "checkout-service"},
        "get_commit": {"commit_hash": "b72d9e1"},
    },
    "sparse_evidence": {
        "search_logs": {
            "service": "checkout-service",
            "level": "ERROR",
        },
        "query_metrics": {
            "service": "checkout-service",
            "metric_name": "error_rate",
        },
        "get_deployments": {"service": "checkout-service"},
    },
}


def evaluate_tool_arguments(case_id: str, steps: list[dict]) -> dict:
    if case_id not in EXPECTED_ARGUMENTS:
        raise ValueError(f"No tool expectations for case: {case_id}")

    expected = EXPECTED_ARGUMENTS[case_id]
    assessments = []

    for index, step in enumerate(steps, start=1):
        decision = step["decision"]
        tool = decision["tool"]

        if tool not in expected:
            verdict = "not_met"
            reason = "Tool is outside this fixture's expected calls."
        elif decision.get("arguments") is None:
            verdict = "not_assessable"
            reason = "Arguments were not recorded."
        elif decision["arguments"] == expected[tool]:
            verdict = "met"
            reason = "Arguments match this fixture's expectation."
        else:
            verdict = "not_met"
            reason = "Arguments differ from this fixture's expectation."

        assessments.append({
            "step": index,
            "tool": tool,
            "verdict": verdict,
            "reason": reason,
        })

    matches = sum(item["verdict"] == "met" for item in assessments)
    assessable = sum(
        item["verdict"] != "not_assessable"
        for item in assessments
    )

    return {
        "case_id": case_id,
        "calls": len(assessments),
        "assessable_calls": assessable,
        "unassessable_calls": len(assessments) - assessable,
        "matching_calls": matches,
        "argument_match_rate": (
            matches / assessable if assessable else None
        ),
        "assessments": assessments,
    }
