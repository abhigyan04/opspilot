import asyncio
import sys
from pathlib import Path
import pytest

from mcp import Client, StdioServerParameters

from app.tools.logs import search_logs
from app.tools.deployments import get_deployments
from app.tools.metrics import query_metrics
from app.tools.git import get_commit


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_search_logs_over_stdio():
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            listed = await client.list_tools()

            tools = {tool.name: tool for tool in listed.tools}
            assert set(tools) == {"search_logs", "get_deployments", "query_metrics", "get_commit"}

            tool = tools["search_logs"]
            assert set(tool.input_schema["required"]) == {"service", "level"}
            assert set(tool.input_schema["properties"]) == {"service", "level"}

            arguments = {
                "service": "checkout-service",
                "level": "ERROR",
            }
            expected = search_logs(**arguments)
            assert expected, "The fixture should contain matching error logs."

            result = await client.call_tool("search_logs", arguments)

            assert result.is_error is False
            assert result.structured_content == {"result": expected}

    asyncio.run(check())


@pytest.mark.parametrize(
    "arguments",
    [
        {"service": "nonexistent-service", "level": "ERROR"},
        {"service": "checkout-service", "level": "NONEXISTENT"},
    ],
)
def test_search_logs_returns_empty_results(arguments):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            result = await client.call_tool("search_logs", arguments)

            assert result.is_error is False
            assert result.structured_content == {"result": []}

    asyncio.run(check())


@pytest.mark.parametrize(
    "arguments",
    [
        {"service": "checkout-service"},  # Missing level.
        {"level": "ERROR"},  # Missing service.
        {"service": ["checkout-service"], "level": "ERROR"},
    ],
)
def test_search_logs_rejects_invalid_arguments(arguments):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            result = await client.call_tool("search_logs", arguments)

            assert result.is_error is True
            assert result.structured_content is None

            # A rejected call must not prevent subsequent valid calls.
            valid_arguments = {
                "service": "checkout-service",
                "level": "ERROR",
            }
            recovery = await client.call_tool("search_logs", valid_arguments)

            assert recovery.is_error is False
            assert recovery.structured_content == {
                "result": search_logs(**valid_arguments),
            }

    asyncio.run(check())


@pytest.mark.parametrize(
    "service",
    ["checkout-service", "nonexistent-service"],
)
def test_get_deployments_over_stdio(service):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            tool = tools["get_deployments"]

            assert set(tool.input_schema["required"]) == {"service"}
            assert set(tool.input_schema["properties"]) == {"service"}

            expected = get_deployments(service=service)
            if service == "checkout-service":
                assert expected
            else:
                assert expected == []

            result = await client.call_tool(
                "get_deployments",
                {"service": service},
            )

            assert result.is_error is False
            assert result.structured_content == {"result": expected}

    asyncio.run(check())


@pytest.mark.parametrize("metric_name", ["error_rate", "nonexistent_metric"])
def test_query_metrics_over_stdio(metric_name):
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            schema = tools["query_metrics"].input_schema

            assert set(schema["required"]) == {"service", "metric_name"}
            assert set(schema["properties"]) == {"service", "metric_name"}

            arguments = {
                "service": "checkout-service",
                "metric_name": metric_name,
            }
            expected = query_metrics(**arguments)
            if metric_name == "error_rate":
                assert expected
            else:
                assert expected == []

            result = await client.call_tool("query_metrics", arguments)

            assert result.is_error is False
            assert result.structured_content == {"result": expected}

    asyncio.run(check())


@pytest.mark.parametrize("existing", [True, False])
def test_get_commit_over_stdio(existing):
    async def check():
        if existing:
            deployments = get_deployments(service="checkout-service")
            assert deployments
            commit_hash = deployments[0]["commit_hash"]
        else:
            commit_hash = "nonexistent-commit"

        expected = get_commit(commit_hash=commit_hash)
        if existing:
            assert expected
        else:
            assert expected is None

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(PROJECT_ROOT),
        )

        async with Client(parameters) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            schema = tools["get_commit"].input_schema

            assert set(schema["required"]) == {"commit_hash"}
            assert set(schema["properties"]) == {"commit_hash"}

            result = await client.call_tool(
                "get_commit",
                {"commit_hash": commit_hash},
            )

            assert result.is_error is False
            assert result.structured_content == {"result": expected}

    asyncio.run(check())
