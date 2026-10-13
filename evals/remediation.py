from app.agent.schemas import RollbackProposal


# Evaluation expectations only. Do not pass these to the agent.
EXPECTED_ROLLBACKS = {
    "checkout_regression": {
        "action": "rollback_service",
        "service": "checkout-service",
        "current_version": "1.7.4",
        "target_version": "1.7.3",
    },
    "payment_provider_outage": None,
    "sparse_evidence": None,
}


def evaluate_rollback_proposal(case_id: str, proposal: RollbackProposal | None) -> dict:
    if case_id not in EXPECTED_ROLLBACKS:
        raise ValueError(f"No remediation expectation for case: {case_id}")

    expected = EXPECTED_ROLLBACKS[case_id]

    actual = (
        proposal.model_dump(include={
            "action",
            "service",
            "current_version",
            "target_version",
        })
        if proposal is not None
        else None
    )

    return {
        "case_id": case_id,
        "expected_proposal": (
            dict(expected) if expected is not None else None
        ),
        "actual_proposal": actual,
        "matches_expectation": actual == expected,
    }
