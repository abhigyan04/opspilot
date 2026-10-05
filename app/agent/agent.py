from ollama import chat

from app.agent.schemas import ToolCall, tool_call_adapter
from app.tools.logs import search_logs
from app.tools.metrics import query_metrics
from app.tools.deployments import get_deployments
from app.tools.git import get_commit


SYSTEM_PROMPT = """
You are OpsPilot, an AI production incident investigator.

Available tools:

search_logs
Arguments:
- service
- level

query_metrics
Arguments:
- service
- metric

get_deployments
Arguments:
- service

get_commit
Arguments:
- commit_hash

Choose the single best tool to call next and provide the arguments
needed to call it.

Important:
- Do not invent argument values.
- Only use information available in the incident.
- If a tool requires information you do not yet know, choose another tool.
- Do not diagnose the incident yet.
- Do not invent evidence.
"""


def choose_next_tool(incident: str) -> ToolCall:
    response = chat(
        model="qwen3:4b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": incident},
        ],
        format=tool_call_adapter.json_schema(),
    )
    return tool_call_adapter.validate_json(response.message.content)


def execute_tool(decision: ToolCall):
    arguments = decision.arguments.model_dump()
    match decision.tool:
        case "search_logs":
            return search_logs(**arguments)
        case "query_metrics":
            return query_metrics(**arguments)
        case "get_deployments":
            return get_deployments(**arguments)
        case "get_commit":
            return get_commit(**arguments)
        case _:
            raise ValueError(f"Unknown tool: {decision.tool}")


if __name__ == "__main__":
    incident = "Errors in checkout-service have increased significantly. Investigate."
    decision = choose_next_tool(incident)
    print(f"Selected tool: {decision.tool}")
    print(f"Arguments: {decision.arguments}")
    print(f"Reason: {decision.reason}")
    result = execute_tool(decision)
    print(f"Tool result: {result}")
