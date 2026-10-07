import pytest
import json

from app.agent.remediation import validate_rollback_target, validate_rollback_evidence, RemediationSession, build_rollback_proposal, review_and_execute
from app.agent.schemas import RollbackProposal, diagnosis_adapter


@pytest.fixture
def deployment():
    return {
        "service": "checkout-service",
        "version": "1.7.4",
        "rollback_target_version": "1.7.3",
    }


def make_proposal(**overrides):
    values = {
        "action": "rollback_service",
        "service": "checkout-service",
        "current_version": "1.7.4",
        "target_version": "1.7.3",
        "reason": "Revert the suspected regression.",
        "evidence_ids": ["evidence-001"],
    }
    values.update(overrides)
    return RollbackProposal(**values)


def test_available_rollback_target_is_accepted(deployment):
    validate_rollback_target(make_proposal(), deployment)


@pytest.mark.parametrize("overrides, message", [
    ({"service": "payment-service"}, "service"),
    ({"current_version": "1.7.2"}, "current version"),
    ({"target_version": "1.7.4"}, "must differ"),
    ({"target_version": "1.7.0"}, "not available"),
])
def test_invalid_rollback_target_is_rejected(deployment, overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_rollback_target(make_proposal(**overrides), deployment)


def test_missing_rollback_target_is_rejected(deployment):
    del deployment["rollback_target_version"]

    with pytest.raises(ValueError, match="not available"):
        validate_rollback_target(make_proposal(), deployment)


def test_rollback_accepts_collected_evidence():
    validate_rollback_evidence(
        make_proposal(),
        [{"evidence_id": "evidence-001"}],
    )


@pytest.mark.parametrize("evidence_ids", [
    ["evidence-999"],
    ["evidence-001", "evidence-999"],
])
def test_rollback_rejects_unknown_evidence(evidence_ids):
    proposal = make_proposal(evidence_ids=evidence_ids)

    with pytest.raises(ValueError, match="evidence-999"):
        validate_rollback_evidence(
            proposal,
            [{"evidence_id": "evidence-001"}],
        )


def test_rollback_rejects_citations_when_no_evidence_was_collected():
    with pytest.raises(ValueError, match="evidence-001"):
        validate_rollback_evidence(make_proposal(), [])


def test_submitted_proposal_requires_explicit_approval(deployment):
    session = RemediationSession()
    proposal_id = session.submit(
        make_proposal(),
        deployment,
        [{"evidence_id": "evidence-001"}],
    )

    assert not session.is_approved(proposal_id)

    session.approve(proposal_id)

    assert session.is_approved(proposal_id)


def test_stored_proposal_is_isolated_from_mutation(deployment):
    session = RemediationSession()
    original = make_proposal()

    proposal_id = session.submit(
        original,
        deployment,
        [{"evidence_id": "evidence-001"}],
    )

    original.target_version = "1.0.0"

    displayed = session.get_proposal(proposal_id)
    assert displayed.target_version == "1.7.3"

    displayed.target_version = "1.1.0"

    assert session.get_proposal(proposal_id).target_version == "1.7.3"


def test_unknown_proposal_cannot_be_approved():
    session = RemediationSession()

    with pytest.raises(ValueError, match="Unknown proposal ID"):
        session.approve("invented-id")


def submit_proposal(session, deployment):
    return session.submit(
        make_proposal(),
        deployment,
        [{"evidence_id": "evidence-001"}],
    )


def test_execution_requires_approval(deployment):
    session = RemediationSession()
    proposal_id = submit_proposal(session, deployment)
    original_state = deployment.copy()

    with pytest.raises(ValueError, match="explicit approval"):
        session.execute(proposal_id, deployment)

    assert deployment == original_state


def test_approved_proposal_updates_simulated_state(deployment):
    session = RemediationSession()
    proposal_id = submit_proposal(session, deployment)
    session.approve(proposal_id)

    result = session.execute(proposal_id, deployment)

    assert result == {
        "status": "simulated",
        "proposal_id": proposal_id,
        "service": "checkout-service",
        "previous_version": "1.7.4",
        "current_version": "1.7.3",
    }
    assert deployment["version"] == "1.7.3"
    assert deployment["rollback_target_version"] is None
    assert not session.is_approved(proposal_id)


@pytest.mark.parametrize("change, message", [
    ({"version": "1.7.5"}, "current version"),
    ({"rollback_target_version": "1.7.2"}, "not available"),
])
def test_execution_rechecks_current_state(deployment, change, message):
    session = RemediationSession()
    proposal_id = submit_proposal(session, deployment)
    session.approve(proposal_id)

    deployment.update(change)
    state_before_execution = deployment.copy()

    with pytest.raises(ValueError, match=message):
        session.execute(proposal_id, deployment)

    assert deployment == state_before_execution


def test_proposal_cannot_execute_twice(deployment):
    session = RemediationSession()
    proposal_id = submit_proposal(session, deployment)
    session.approve(proposal_id)
    session.execute(proposal_id, deployment)

    state_after_execution = deployment.copy()

    with pytest.raises(ValueError, match="already been executed"):
        session.execute(proposal_id, deployment)

    assert deployment == state_after_execution


@pytest.mark.parametrize("deployment_count", [0, 1, 2])
def test_proposal_requires_unambiguous_deployment(deployment, deployment_count):
    diagnosis = diagnosis_adapter.validate_python({
        "status": "supported",
        "root_cause": {
            "statement": "The deployed change likely introduced the failure.",
            "evidence_ids": ["evidence-001"],
        },
        "supporting_claims": [],
        "limitations": ["Requires human assessment before rollback."],
    })

    steps = [{
        "evidence_id": "evidence-001",
        "decision": {"tool": "get_deployments"},
        "result": [deployment.copy() for _ in range(deployment_count)],
    }]

    proposal = build_rollback_proposal(
        diagnosis, "checkout-service", steps
    )

    if deployment_count == 1:
        assert proposal.current_version == "1.7.4"
        assert proposal.target_version == "1.7.3"
        assert proposal.evidence_ids == ["evidence-001"]
    else:
        assert proposal is None


def test_insufficient_diagnosis_produces_no_rollback_proposal():
    diagnosis = diagnosis_adapter.validate_python({
        "status": "insufficient_evidence",
        "reason": "The cause is unknown.",
        "missing_evidence": ["Application logs"],
    })

    assert build_rollback_proposal(
        diagnosis, "checkout-service", []
    ) is None


@pytest.mark.parametrize("approve", [False, True])
def test_review_requires_exact_approval(deployment, approve):
    displayed = []
    original_state = deployment.copy()

    def fake_input(prompt):
        proposal_id = json.loads(displayed[0])["proposal_id"]
        assert proposal_id in prompt

        if approve:
            return f"approve {proposal_id}"
        return "yes"

    result = review_and_execute(
        make_proposal(),
        [{"evidence_id": "evidence-001"}],
        deployment,
        input_fn=fake_input,
        output_fn=displayed.append,
    )

    if approve:
        assert result["status"] == "simulated"
        assert deployment["version"] == "1.7.3"
    else:
        assert result["status"] == "declined"
        assert deployment == original_state


@pytest.mark.parametrize("error_type", [EOFError, KeyboardInterrupt])
def test_interrupted_review_declines_without_execution(deployment, error_type):
    original_state = deployment.copy()

    def interrupted_input(prompt):
        raise error_type()

    result = review_and_execute(
        make_proposal(),
        [{"evidence_id": "evidence-001"}],
        deployment,
        input_fn=interrupted_input,
        output_fn=lambda message: None,
    )

    assert result["status"] == "declined"
    assert deployment == original_state


@pytest.mark.parametrize("answer", ["", "approve wrong-id"])
def test_invalid_approval_declines_without_execution(deployment, answer):
    original_state = deployment.copy()

    result = review_and_execute(
        make_proposal(),
        [{"evidence_id": "evidence-001"}],
        deployment,
        input_fn=lambda prompt: answer,
        output_fn=lambda message: None,
    )

    assert result["status"] == "declined"
    assert deployment == original_state
