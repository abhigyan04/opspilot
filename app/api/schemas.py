from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StartWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    incident: str = Field(min_length=1, max_length=4000)
    scenario: Literal[
        "checkout_regression",
        "payment_provider_outage",
        "sparse_evidence",
    ] = "checkout_regression"
    tool_backend: Literal["direct", "mcp"] = "direct"

    @field_validator("incident")
    @classmethod
    def reject_blank_incident(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Incident must contain non-whitespace text.")
        return value


class ReviewWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proposal_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approve", "decline"]

    @field_validator("proposal_id")
    @classmethod
    def reject_whitespace_in_proposal_id(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Proposal ID must not contain whitespace.")
        return value
