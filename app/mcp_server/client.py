import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import Client, StdioServerParameters

from app.agent.schemas import ToolCall


PROJECT_ROOT = Path(__file__).resolve().parents[2]

INVESTIGATION_TOOLS = frozenset({
    "search_logs",
    "query_metrics",
    "get_deployments",
    "get_commit",
})


class MCPToolError(RuntimeError):
    """An MCP tool failed or returned an unexpected response."""


class MCPToolExecutor:
    def __init__(self, client: Client):
        self._client = client

    async def execute(self, decision: ToolCall):
        if decision.tool not in INVESTIGATION_TOOLS:
            raise ValueError(f"Unknown investigation tool: {decision.tool}")

        response = await self._client.call_tool(
            decision.tool,
            decision.arguments.model_dump(),
        )

        if response.is_error:
            raise MCPToolError(f"MCP tool failed: {decision.tool}")

        payload = response.structured_content
        if not isinstance(payload, dict) or "result" not in payload:
            raise MCPToolError(
                f"MCP tool returned no structured result: {decision.tool}"
            )

        result = payload["result"]

        if decision.tool == "get_commit":
            valid = result is None or isinstance(result, dict)
        else:
            valid = (
                isinstance(result, list)
                and all(isinstance(item, dict) for item in result)
            )

        if not valid:
            raise MCPToolError(
                f"MCP tool returned an invalid result shape: {decision.tool}"
            )

        return result


@asynccontextmanager
async def connect_local_tools():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server.server"],
        cwd=str(PROJECT_ROOT),
    )

    async with Client(parameters) as client:
        yield MCPToolExecutor(client)
