import pytest

from app.agent.schemas import RollbackProposal
from evals.remediation import evaluate_rollback_proposal


def make_proposal(**overrides):
    return RollbackProposal.model_validate({
        "action": "rollback_service",
        "service": "checkout-service",
        "current_version": "1.7.4",
        "target_version": "1.7.3",
        "reason": "Synthetic proposal for evaluator testing.",
        "evidence_ids": ["evidence-001"],
        **overrides,
    })


@pytest.mark.parametrize(
    "case_id, proposal_fields, expected_match",
    [
        ("checkout_regression", {}, True),
        ("checkout_regression", None, False),
        (
            "checkout_regression",
            {"target_version": "1.7.2"},
            False,
        ),
        (
            "checkout_regression",
            {"service": "another-service"},
            False,
        ),
        (
            "checkout_regression",
            {"current_version": "1.7.5"},
            False,
        ),
        ("payment_provider_outage", None, True),
        ("payment_provider_outage", {}, False),
        ("sparse_evidence", None, True),
        ("sparse_evidence", {}, False),
    ],
)
def test_rollback_evaluation_checks_scenario_and_target(case_id, proposal_fields, expected_match):
    proposal = (
        make_proposal(**proposal_fields)
        if proposal_fields is not None
        else None
    )

    result = evaluate_rollback_proposal(case_id, proposal)

    assert result["case_id"] == case_id
    assert result["matches_expectation"] is expected_match
    assert (result["actual_proposal"] is None) == (proposal is None)


def test_unknown_case_is_not_silently_scored():
    with pytest.raises(ValueError, match="No remediation expectation"):
        evaluate_rollback_proposal("unknown_case", None)
