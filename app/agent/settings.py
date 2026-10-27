import os

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_INVESTIGATION_MODEL = "qwen3:4b"
DEFAULT_DIAGNOSIS_MODEL = "qwen3:4b"
DEFAULT_WORKFLOW_DIAGNOSIS_MODEL = "qwen3:8b"
DEFAULT_SERVICE = "checkout-service"


class RuntimeSettings(BaseModel):
    """Validated process configuration; .env files are not loaded implicitly."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    investigation_model: str = Field(default=DEFAULT_INVESTIGATION_MODEL, min_length=1)
    diagnosis_model: str = Field(default=DEFAULT_DIAGNOSIS_MODEL, min_length=1)
    workflow_diagnosis_model: str = Field(default=DEFAULT_WORKFLOW_DIAGNOSIS_MODEL, min_length=1)
    service: str = Field(default=DEFAULT_SERVICE, min_length=1)
    max_steps: int = Field(default=6, gt=0)
    workflow_num_ctx: int = Field(default=8192, gt=0)
    workflow_num_predict: int = Field(default=2048, gt=0)

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls.model_validate({
            name: os.environ[key]
            for name in cls.model_fields
            if (key := f"OPSPILOT_{name.upper()}") in os.environ
        })


class DiagnosisSettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )

    num_ctx: int = Field(default=4096, gt=0)
    num_predict: int = Field(default=2048, gt=0)
    temperature: float = Field(default=0.6, ge=0)
    top_p: float = Field(default=0.95, gt=0, le=1)
    top_k: int = Field(default=20, gt=0)
    seed: int = Field(default=42, ge=0)
    think: bool = True

    def ollama_options(self) -> dict:
        return self.model_dump(exclude={"think"})
