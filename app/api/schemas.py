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
