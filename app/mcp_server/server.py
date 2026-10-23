import argparse

from mcp.server import MCPServer

from app.tools.data import SCENARIOS_ROOT
from app.tools.logs import search_logs as search_fixture_logs
from app.tools.deployments import get_deployments as get_fixture_deployments
from app.tools.metrics import query_metrics as query_fixture_metrics
from app.tools.git import get_commit as get_fixture_commit


SUPPORTED_SCENARIOS = (
    "checkout_regression",
    "payment_provider_outage",
    "sparse_evidence",
)


def create_server(scenario: str = "checkout_regression") -> MCPServer:
    if scenario not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unsupported MCP scenario: {scenario}")

    data_dir = SCENARIOS_ROOT / scenario
    instance = MCPServer("OpsPilot operational tools")

    @instance.tool()
    def search_logs(service: str, level: str) -> list[dict]:
        """Search synthetic logs in the configured scenario."""
        return search_fixture_logs(
            service=service,
            level=level,
            data_dir=data_dir,
        )

    @instance.tool()
    def get_deployments(service: str) -> list[dict]:
        """Get synthetic deployments in the configured scenario."""
        return get_fixture_deployments(
            service=service,
            data_dir=data_dir,
        )

    @instance.tool()
    def query_metrics(service: str, metric_name: str) -> list[dict]:
        """Query synthetic metrics in the configured scenario."""
        return query_fixture_metrics(
            service=service,
            metric_name=metric_name,
            data_dir=data_dir,
        )

    @instance.tool()
    def get_commit(commit_hash: str) -> dict | None:
        """Get a synthetic commit in the configured scenario."""
        return get_fixture_commit(
            commit_hash=commit_hash,
            data_dir=data_dir,
        )

    return instance


# Preserve the existing importable default server.
server = create_server()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Serve OpsPilot synthetic investigation tools over MCP."
    )
    parser.add_argument(
        "--scenario",
        choices=SUPPORTED_SCENARIOS,
        default="checkout_regression",
    )
    args = parser.parse_args(argv)
    create_server(args.scenario).run(transport="stdio")


if __name__ == "__main__":
    main()
