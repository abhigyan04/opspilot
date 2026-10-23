import asyncio
from types import SimpleNamespace
import pytest

from app.agent.schemas import (
    GetCommitArguments,
    GetCommitCall,
    GetDeploymentsArguments,
    GetDeploymentsCall,
)
from app.mcp_server.client import connect_local_tools, MCPToolError, MCPToolExecutor
from app.tools.deployments import get_deployments
from app.tools.git import get_commit
from app.tools.data import SCENARIOS_ROOT


def test_executor_chains_deployment_and_commit_calls():
    async def check():
        deployment_call = GetDeploymentsCall(
            tool="get_deployments",
            arguments=GetDeploymentsArguments(service="checkout-service"),
            reason="Find the deployed commit.",
        )

        async with connect_local_tools() as executor:
            deployments = await executor.execute(deployment_call)

            assert deployments == get_deployments(service="checkout-service")
            assert deployments

            commit_hash = deployments[0]["commit_hash"]
            commit_call = GetCommitCall(
                tool="get_commit",
                arguments=GetCommitArguments(commit_hash=commit_hash),
                reason="Inspect the deployed commit.",
            )

            commit = await executor.execute(commit_call)

            assert commit is not None
            assert commit == get_commit(commit_hash=commit_hash)

    asyncio.run(check())


def test_executor_preserves_missing_commit():
    async def check():
        decision = GetCommitCall(
            tool="get_commit",
            arguments=GetCommitArguments(commit_hash="nonexistent-commit"),
            reason="Check an unknown commit.",
        )

        async with connect_local_tools() as executor:
            assert await executor.execute(decision) is None

    asyncio.run(check())


class StubClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.response


def make_deployment_call():
    return GetDeploymentsCall(
        tool="get_deployments",
        arguments=GetDeploymentsArguments(service="checkout-service"),
        reason="Inspect deployments.",
    )


def test_executor_rejects_tool_error_even_with_result():
    client = StubClient(
        response=SimpleNamespace(
            is_error=True,
            structured_content={"result": []},
        )
    )

    with pytest.raises(MCPToolError, match="MCP tool failed"):
        asyncio.run(MCPToolExecutor(client).execute(make_deployment_call()))


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"unexpected": []},
    ],
)
def test_executor_rejects_missing_result_envelope(payload):
    client = StubClient(
        response=SimpleNamespace(
            is_error=False,
            structured_content=payload,
        )
    )

    with pytest.raises(MCPToolError, match="no structured result"):
        asyncio.run(MCPToolExecutor(client).execute(make_deployment_call()))


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        "not a list",
        [123],
        [{"service": "checkout-service"}, "invalid row"],
    ],
)
def test_executor_rejects_invalid_list_result(result):
    client = StubClient(
        response=SimpleNamespace(
            is_error=False,
            structured_content={"result": result},
        )
    )

    with pytest.raises(MCPToolError, match="invalid result shape"):
        asyncio.run(MCPToolExecutor(client).execute(make_deployment_call()))


@pytest.mark.parametrize("result", [[], "not a commit", 123])
def test_executor_rejects_invalid_commit_result(result):
    decision = GetCommitCall(
        tool="get_commit",
        arguments=GetCommitArguments(commit_hash="example"),
        reason="Inspect commit.",
    )
    client = StubClient(
        response=SimpleNamespace(
            is_error=False,
            structured_content={"result": result},
        )
    )

    with pytest.raises(MCPToolError, match="invalid result shape"):
        asyncio.run(MCPToolExecutor(client).execute(decision))


def test_executor_propagates_transport_failure():
    failure = ConnectionError("Test connection closed.")
    client = StubClient(error=failure)

    with pytest.raises(ConnectionError) as caught:
        asyncio.run(MCPToolExecutor(client).execute(make_deployment_call()))

    assert caught.value is failure
    assert client.calls == [
        ("get_deployments", {"service": "checkout-service"}),
    ]


def test_executor_rejects_unknown_tool_before_calling_client():
    # Deliberately bypass the normal validated ToolCall schema.
    decision = SimpleNamespace(tool="rollback_service")
    client = StubClient()

    with pytest.raises(ValueError, match="Unknown investigation tool"):
        asyncio.run(MCPToolExecutor(client).execute(decision))

    assert client.calls == []


@pytest.mark.parametrize(
    "scenario",
    ["checkout_regression", "payment_provider_outage", "sparse_evidence"],
)
def test_client_selects_scenario(scenario):
    async def check():
        decision = make_deployment_call()
        expected = get_deployments(
            service="checkout-service",
            data_dir=SCENARIOS_ROOT / scenario,
        )

        async with connect_local_tools(scenario=scenario) as executor:
            actual = await executor.execute(decision)

        assert actual == expected

    asyncio.run(check())
