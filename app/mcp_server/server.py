from mcp.server import MCPServer

from app.tools.logs import search_logs as search_fixture_logs
from app.tools.deployments import get_deployments as get_fixture_deployments
from app.tools.metrics import query_metrics as query_fixture_metrics
from app.tools.git import get_commit as get_fixture_commit


server = MCPServer("OpsPilot operational tools")


@server.tool()
def search_logs(service: str, level: str) -> list[dict]:
    """Search synthetic checkout-regression logs by service and exact log level."""
    return search_fixture_logs(service=service, level=level)


@server.tool()
def get_deployments(service: str) -> list[dict]:
    """Get synthetic checkout-regression deployments for a service."""
    return get_fixture_deployments(service=service)


@server.tool()
def query_metrics(service: str, metric_name: str) -> list[dict]:
    """Query synthetic checkout-regression metrics by service and metric name."""
    return query_fixture_metrics(service=service, metric_name=metric_name)


@server.tool()
def get_commit(commit_hash: str) -> dict | None:
    """Get a synthetic checkout-regression commit by its hash."""
    return get_fixture_commit(commit_hash=commit_hash)


if __name__ == "__main__":
    server.run(transport="stdio")
