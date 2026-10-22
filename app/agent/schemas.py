from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, AwareDatetime, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


DiagnosisText = Annotated[
    str,
    Field(min_length=1, max_length=600),
]


class EvidenceClaim(StrictModel):
    statement: DiagnosisText
    evidence_ids: list[str] = Field(min_length=1, max_length=12)


class ReferenceNote(StrictModel):
    statement: DiagnosisText
    reference_ids: list[str] = Field(min_length=1, max_length=3)


class SupportedDiagnosis(StrictModel):
    status: Literal["supported"]
    root_cause: EvidenceClaim
    supporting_claims: list[EvidenceClaim] = Field(max_length=6)
    limitations: list[DiagnosisText] = Field(max_length=4)
    reference_notes: list[ReferenceNote] = Field(
        default_factory=list,
        max_length=3,
    )

    @model_validator(mode="after")
    def reject_duplicate_claims(self):
        statements = [
            self.root_cause.statement,
            *[claim.statement for claim in self.supporting_claims],
        ]
        normalized = [
            " ".join(statement.split()).casefold()
            for statement in statements
        ]

        if len(normalized) != len(set(normalized)):
            raise ValueError("Diagnosis contains duplicate claims.")

        return self


class InsufficientEvidence(StrictModel):
    status: Literal["insufficient_evidence"]
    reason: DiagnosisText
    missing_evidence: list[DiagnosisText] = Field(
        min_length=1,
        max_length=6,
    )
    reference_notes: list[ReferenceNote] = Field(
        default_factory=list,
        max_length=3,
    )


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


class ErrorRateSample(StrictModel):
    service: str = Field(min_length=1)
    metric: Literal["error_rate"]
    timestamp: AwareDatetime
    value: float = Field(ge=0, le=1, allow_inf_nan=False)


class RecoveryWindow(StrictModel):
    service: str = Field(min_length=1)
    action_completed_at: AwareDatetime
    observed_at: AwareDatetime
    samples: list[ErrorRateSample]

    @model_validator(mode="after")
    def validate_time_order(self):
        if self.observed_at < self.action_completed_at:
            raise ValueError("Observation time cannot precede action completion.")
        return self
