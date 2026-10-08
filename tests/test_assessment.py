import pytest
import hashlib
import json

from pydantic import ValidationError

from evals.assessment import DiagnosisReview, save_review


def review_payload():
    return {
        "run_id": "example-run",
        "case_id": "payment_provider_outage",
        "reviewer": "Abhigyan",
        "causal_explanation": {
            "verdict": "met",
            "rationale": "Identifies provider HTTP 503 responses.",
        },
        "deployment_reasoning": {
            "verdict": "met",
            "rationale": "Recognizes failures before deployment.",
        },
        "evidence_grounding": {
            "verdict": "not_met",
            "rationale": "Invents a reason for the logging deployment.",
        },
        "uncertainty_handling": {
            "verdict": "not_met",
            "rationale": (
                "Treats unknown provider internals as preventing "
                "identification of the checkout failure mechanism."
            ),
        },
    }


def test_review_preserves_separate_criterion_results():
    review = DiagnosisReview.model_validate(review_payload())

    assert review.causal_explanation.verdict == "met"
    assert review.evidence_grounding.verdict == "not_met"


def test_review_rejects_unknown_verdict():
    payload = review_payload()
    payload["causal_explanation"]["verdict"] = "probably"

    with pytest.raises(ValidationError):
        DiagnosisReview.model_validate(payload)


def test_review_requires_every_criterion():
    payload = review_payload()
    del payload["uncertainty_handling"]

    with pytest.raises(ValidationError):
        DiagnosisReview.model_validate(payload)


def test_review_requires_nonblank_rationale():
    payload = review_payload()
    payload["evidence_grounding"]["rationale"] = "   "

    with pytest.raises(ValidationError):
        DiagnosisReview.model_validate(payload)


def write_report(tmp_path, *, diagnosis_present=True):
    report = {
        "report_version": 2,
        "run_id": "example-run",
        "case_id": "payment_provider_outage",
        "status": "completed" if diagnosis_present else "failed",
        "diagnosis": (
            {
                "status": "insufficient_evidence",
                "reason": "Provider internals are unknown.",
                "missing_evidence": ["Provider diagnostics"],
            }
            if diagnosis_present else None
        ),
    }
    path = tmp_path / "example-run.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_review_is_saved_without_changing_report(tmp_path):
    report_path = write_report(tmp_path)
    original = report_path.read_bytes()
    review = DiagnosisReview.model_validate(review_payload())

    destination = save_review(review, report_path)
    saved = json.loads(destination.read_text(encoding="utf-8"))

    assert destination.name == "example-run.review.json"
    assert report_path.read_bytes() == original
    assert saved["review"] == review.model_dump(mode="json")
    assert saved["source_sha256"] == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize("field", ["run_id", "case_id"])
def test_review_rejects_mismatched_identity(tmp_path, field):
    report_path = write_report(tmp_path)
    payload = review_payload()
    payload[field] = "different"
    review = DiagnosisReview.model_validate(payload)

    with pytest.raises(ValueError, match=field):
        save_review(review, report_path)

    assert not report_path.with_suffix(".review.json").exists()


def test_existing_review_is_not_overwritten(tmp_path):
    report_path = write_report(tmp_path)
    review = DiagnosisReview.model_validate(review_payload())
    destination = save_review(review, report_path)
    original = destination.read_bytes()

    with pytest.raises(FileExistsError):
        save_review(review, report_path)

    assert destination.read_bytes() == original


def test_missing_diagnosis_cannot_receive_substantive_grades(tmp_path):
    report_path = write_report(tmp_path, diagnosis_present=False)
    review = DiagnosisReview.model_validate(review_payload())

    with pytest.raises(ValueError, match="not_assessable"):
        save_review(review, report_path)
