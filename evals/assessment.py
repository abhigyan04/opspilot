from typing import Literal
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ReviewModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class CriterionReview(ReviewModel):
    verdict: Literal["met", "not_met", "not_assessable"]
    rationale: str = Field(min_length=1)


class DiagnosisReview(ReviewModel):
    rubric_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    causal_explanation: CriterionReview
    deployment_reasoning: CriterionReview
    evidence_grounding: CriterionReview
    uncertainty_handling: CriterionReview


def save_review(review: DiagnosisReview, report_path: Path) -> Path:
    original_bytes = report_path.read_bytes()
    report = json.loads(original_bytes)

    if report.get("report_version") != 2:
        raise ValueError("Review requires a version 2 run report.")

    if review.run_id != report["run_id"]:
        raise ValueError("Review run_id does not match the report.")

    if review.case_id != report["case_id"]:
        raise ValueError("Review case_id does not match the report.")

    if report.get("diagnosis") is None:
        criteria = (
            review.causal_explanation,
            review.deployment_reasoning,
            review.evidence_grounding,
            review.uncertainty_handling,
        )
        if any(
            criterion.verdict != "not_assessable"
            for criterion in criteria
        ):
            raise ValueError(
                "A missing diagnosis requires not_assessable for every criterion."
            )

    record = {
        "source_report": report_path.name,
        "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "review": review.model_dump(mode="json"),
    }
    destination = report_path.with_suffix(".review.json")

    with destination.open("x", encoding="utf-8") as output:
        json.dump(record, output, indent=2)
        output.write("\n")

    return destination
