from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchLogsArguments(StrictModel):
    service: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class QueryMetricsArguments(StrictModel):
    service: str
    metric_name: str


class GetDeploymentsArguments(StrictModel):
    service: str


class GetCommitArguments(StrictModel):
    commit_hash: str


class SearchLogsCall(StrictModel):
    tool: Literal["search_logs"]
    arguments: SearchLogsArguments
    reason: str


class QueryMetricsCall(StrictModel):
    tool: Literal["query_metrics"]
    arguments: QueryMetricsArguments
    reason: str


class GetDeploymentsCall(StrictModel):
    tool: Literal["get_deployments"]
    arguments: GetDeploymentsArguments
    reason: str


class GetCommitCall(StrictModel):
    tool: Literal["get_commit"]
    arguments: GetCommitArguments
    reason: str


ToolCall = Annotated[
    SearchLogsCall | QueryMetricsCall | GetDeploymentsCall | GetCommitCall,
    Field(discriminator="tool"),
]
tool_call_adapter = TypeAdapter(ToolCall)
