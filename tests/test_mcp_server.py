import asyncio
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from app.tools.logs import search_logs


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

            assert [tool.name for tool in listed.tools] == ["search_logs"]

            tool = listed.tools[0]
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
