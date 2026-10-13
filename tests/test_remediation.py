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
def test_proposal_requires_unambiguous_deployment(rollback_context, deployment_count):
    diagnosis, steps = rollback_context
    deployment_record = steps[0]["result"][0]
    steps[0]["result"] = [
        deployment_record.copy()
        for _ in range(deployment_count)
    ]

    proposal = build_rollback_proposal(
        diagnosis, "checkout-service", steps
    )

    if deployment_count == 1:
        assert proposal is not None
        assert proposal.current_version == "1.7.4"
        assert proposal.target_version == "1.7.3"
        assert proposal.evidence_ids == ["evidence-001", "evidence-002"]
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


@pytest.fixture
def rollback_context(deployment):
    deployment_record = {
        **deployment,
        "commit_hash": "commit-123",
    }
    diagnosis = diagnosis_adapter.validate_python({
        "status": "supported",
        "root_cause": {
            "statement": (
                "The deployed customer lookup can raise AttributeError "
                "when request.user is None."
            ),
            "evidence_ids": ["evidence-001", "evidence-002"],
        },
        "supporting_claims": [],
        "limitations": ["Requires human assessment before rollback."],
    })
    steps = [
        {
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "get_deployments",
                "arguments": {"service": "checkout-service"},
            },
            "result": [deployment_record],
        },
        {
            "evidence_id": "evidence-002",
            "decision": {
                "tool": "get_commit",
                "arguments": {"commit_hash": "commit-123"},
            },
            "result": {
                "hash": "commit-123",
                "diff": (
                    "- customer_id = request.customer_id\n"
                    "+ customer_id = request.user.customer_id"
                ),
            },
        },
    ]
    return diagnosis, steps


@pytest.mark.parametrize("root_ids", [
    ["evidence-001"],  # Deployment without its code change.
    ["evidence-002"],  # Code change without its deployment.
])
def test_proposal_requires_both_root_cause_citations(rollback_context, root_ids):
    diagnosis, steps = rollback_context
    diagnosis.root_cause.evidence_ids = root_ids

    # Supporting citations must not substitute for root-cause citations.
    diagnosis.supporting_claims = [
        diagnosis.root_cause.model_copy(update={
            "evidence_ids": ["evidence-001", "evidence-002"],
        })
    ]

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


@pytest.mark.parametrize("mismatch", ["request", "result"])
def test_proposal_rejects_unrelated_commit(rollback_context, mismatch):
    diagnosis, steps = rollback_context

    if mismatch == "request":
        steps[1]["decision"]["arguments"]["commit_hash"] = "other-commit"
    else:
        steps[1]["result"]["hash"] = "other-commit"

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


@pytest.mark.parametrize("diff", [None, "", "   "])
def test_proposal_requires_available_code_change(rollback_context, diff):
    diagnosis, steps = rollback_context
    steps[1]["result"]["diff"] = diff

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


def test_proposal_requires_deployment_commit_hash(rollback_context):
    diagnosis, steps = rollback_context
    del steps[0]["result"][0]["commit_hash"]

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


def test_provider_log_citation_does_not_justify_rollback(rollback_context):
    diagnosis, steps = rollback_context
    diagnosis.root_cause.statement = (
        "Checkout payment authorization fails because PayBridge returns 503."
    )
    diagnosis.root_cause.evidence_ids = ["evidence-003"]
    steps.append({
        "evidence_id": "evidence-003",
        "decision": {
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
        },
        "result": [{
            "message": "Payment authorization failed: PayBridge HTTP 503",
        }],
    })

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


@pytest.fixture
def preexisting_failure_context(rollback_context):
    diagnosis, steps = rollback_context

    steps[0]["result"][0]["timestamp"] = "2026-09-28T13:57:00Z"
    steps[1]["result"]["diff"] = (
        " def checkout(request):\n"
        '+    logger.info("Checkout request received")\n'
        "     return process_checkout(request)"
    )

    diagnosis.root_cause.statement = (
        "Checkout payment authorization fails because PayBridge returns 503."
    )
    diagnosis.root_cause.evidence_ids = [
        "evidence-001",  # Deployment.
        "evidence-002",  # Matching commit, but only a logging change.
        "evidence-003",  # Failures before and after deployment.
    ]

    steps.append({
        "evidence_id": "evidence-003",
        "decision": {
            "tool": "search_logs",
            "arguments": {
                "service": "checkout-service",
                "level": "ERROR",
            },
        },
        "result": [
            {
                "timestamp": "2026-09-28T13:54:00Z",
                "service": "checkout-service",
                "version": "1.7.3",
                "level": "ERROR",
                "message": (
                    "Payment authorization failed: "
                    "provider PayBridge returned HTTP 503"
                ),
            },
            {
                "timestamp": "2026-09-28T14:02:00Z",
                "service": "checkout-service",
                "version": "1.7.4",
                "level": "ERROR",
                "message": (
                    "Payment authorization failed: "
                    "provider PayBridge returned HTTP 503"
                ),
            },
        ],
    })

    return diagnosis, steps


def test_predeployment_provider_failures_block_rollback_despite_citations(preexisting_failure_context):
    diagnosis, steps = preexisting_failure_context

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


@pytest.mark.parametrize("record_index, field, value", [
    (0, "message", "An unrelated earlier error"),
    (0, "service", "another-service"),
    (1, "service", "another-service"),
    (0, "version", "1.7.2"),
    (1, "version", "1.7.5"),
    (0, "level", "INFO"),
    (0, "timestamp", "2026-09-28T13:58:00Z"),
    (0, "timestamp", "2026-09-28T13:57:00Z"),
    (1, "timestamp", "2026-09-28T13:56:00Z"),
    (1, "timestamp", "2026-09-28T13:57:00Z"),
])
def test_unmatched_log_pair_does_not_trigger_timeline_block(preexisting_failure_context, record_index, field, value):
    diagnosis, steps = preexisting_failure_context
    steps[-1]["result"][record_index][field] = value

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is not None


def test_timeline_check_compares_timezone_aware_instants(preexisting_failure_context):
    diagnosis, steps = preexisting_failure_context
    steps[-1]["result"][0]["timestamp"] = "2026-09-28T15:54:00+02:00"
    steps[-1]["result"][1]["timestamp"] = "2026-09-28T09:02:00-05:00"

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


def test_uncited_logs_still_supply_contradictory_evidence(preexisting_failure_context):
    diagnosis, steps = preexisting_failure_context
    diagnosis.root_cause.evidence_ids = ["evidence-001", "evidence-002"]

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is None


@pytest.mark.parametrize("timestamp", [
    None,
    "not-a-timestamp",
    "2026-09-28T13:54:00",  # Missing timezone.
])
def test_unusable_log_time_does_not_establish_timeline_contradiction(preexisting_failure_context, timestamp):
    diagnosis, steps = preexisting_failure_context
    steps[-1]["result"][0]["timestamp"] = timestamp

    assert build_rollback_proposal(
        diagnosis, "checkout-service", steps
    ) is not None
