from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceClaim(StrictModel):
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class SupportedDiagnosis(StrictModel):
    status: Literal["supported"]
    root_cause: EvidenceClaim
    supporting_claims: list[EvidenceClaim]
    limitations: list[str]


class InsufficientEvidence(StrictModel):
    status: Literal["insufficient_evidence"]
    reason: str = Field(min_length=1)
    missing_evidence: list[str] = Field(min_length=1)


Diagnosis = Annotated[
    SupportedDiagnosis | InsufficientEvidence,
    Field(discriminator="status"),
]

diagnosis_adapter = TypeAdapter(Diagnosis)


class SearchLogsArguments(StrictModel):
    service: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class QueryMetricsArguments(StrictModel):
    service: str
    metric_name: Literal["error_rate"]


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

class FinishInvestigation(StrictModel):
    tool: Literal["finish"]
    reason: str


AgentDecision = Annotated[
    SearchLogsCall
    | QueryMetricsCall
    | GetDeploymentsCall
    | GetCommitCall
    | FinishInvestigation,
    Field(discriminator="tool"),
]

agent_decision_adapter = TypeAdapter(AgentDecision)

class RollbackProposal(StrictModel):
    action: Literal["rollback_service"]
    service: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    target_version: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
