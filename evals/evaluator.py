from evals.cases import EvaluationCase


def evaluate_investigation(case: EvaluationCase, investigation: dict) -> dict:
    used_tools = {
        step["decision"]["tool"]
        for step in investigation["steps"]
    }

    missing_tools = case.required_tools - used_tools
    covered_tools = case.required_tools & used_tools

    coverage = (
        len(covered_tools) / len(case.required_tools)
        if case.required_tools
        else 1.0
    )

    return {
        "case_id": case.case_id,
        "required_tool_coverage": coverage,
        "missing_tools": sorted(missing_tools),
        "tool_calls": len(investigation["steps"]),
        "stopped_by_model": investigation["status"] == "finished",
        "hit_step_limit": investigation["status"] == "step_limit",
    }
