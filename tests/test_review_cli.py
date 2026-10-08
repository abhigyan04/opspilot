import pytest

from evals.review import collect_review


def sample_report():
    return {
        "report_version": 2,
        "run_id": "review-test",
        "case_id": "payment_provider_outage",
        "diagnosis": {
            "status": "insufficient_evidence",
            "reason": "Provider internals are unknown.",
            "missing_evidence": ["Provider diagnostics"],
        },
    }


def test_collect_review_preserves_human_judgments():
    answers = iter([
        "1", "Identifies provider errors.",
        "1", "Recognizes failures before deployment.",
        "2", "Invents the motivation for deployment.",
        "2", "Abstains despite an identifiable checkout failure mechanism.",
    ])
    displayed = []

    review = collect_review(
        sample_report(),
        "Abhigyan",
        input_fn=lambda prompt: next(answers),
        output_fn=displayed.append,
    )

    assert review.run_id == "review-test"
    assert review.reviewer == "Abhigyan"
    assert review.causal_explanation.verdict == "met"
    assert review.evidence_grounding.verdict == "not_met"
    assert "Provider internals are unknown." in displayed[0]


def test_invalid_choice_and_blank_rationale_are_reprompted():
    answers = iter([
        "invalid", "1", "   ", "Supported mechanism.",
        "1", "Correct timeline.",
        "1", "Claims grounded.",
        "1", "Appropriate limitations.",
    ])
    displayed = []

    review = collect_review(
        sample_report(),
        "Abhigyan",
        input_fn=lambda prompt: next(answers),
        output_fn=displayed.append,
    )

    assert review.causal_explanation.rationale == "Supported mechanism."
    assert "Enter 1, 2, or 3." in displayed
    assert "A nonblank rationale is required." in displayed


def test_interrupted_collection_returns_no_partial_review():
    def interrupted_input(prompt):
        raise EOFError()

    with pytest.raises(EOFError):
        collect_review(
            sample_report(),
            "Abhigyan",
            input_fn=interrupted_input,
            output_fn=lambda message: None,
        )
