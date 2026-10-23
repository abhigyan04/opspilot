from mcp.server import MCPServer

from app.tools.logs import search_logs as search_fixture_logs


server = MCPServer("OpsPilot operational tools")


@server.tool()
def search_logs(service: str, level: str) -> list[dict]:
    """Search synthetic checkout-regression logs by service and exact log level."""
    return search_fixture_logs(service=service, level=level)


if __name__ == "__main__":
    server.run(transport="stdio")
