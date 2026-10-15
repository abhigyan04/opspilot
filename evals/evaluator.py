from evals.cases import CASES, EvaluationCase
from evals.evidence_assessment import evaluate_evidence_content
from evals.tool_assessment import evaluate_tool_arguments


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
    
    if case == CASES.get(case.case_id):
        tool_arguments = {
            "status": "scored",
            **evaluate_tool_arguments(case.case_id, investigation["steps"]),
        }
        evidence_content = {
            "status": "scored",
            **evaluate_evidence_content(case.case_id, investigation["steps"]),
        }
    else:
        tool_arguments = {
            "status": "not_scored",
            "reason": "Case configuration has no registered expectations.",
        }
        evidence_content = {
            "status": "not_scored",
            "reason": "Case configuration has no registered expectations.",
        }

    return {
        "case_id": case.case_id,
        "required_tool_coverage": coverage,
        "missing_tools": sorted(missing_tools),
        "tool_calls": len(investigation["steps"]),
        "stopped_by_model": investigation["status"] == "finished",
        "hit_step_limit": investigation["status"] == "step_limit",
        "tool_arguments": tool_arguments,
        "evidence_content": evidence_content
    }
