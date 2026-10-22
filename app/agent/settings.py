from pydantic import BaseModel, ConfigDict, Field


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
