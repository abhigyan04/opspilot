import pytest
from pydantic import ValidationError

from app.agent.schemas import ErrorRateSample, RecoveryWindow
from app.agent.verification import verify_recovery
from app.agent import verification
from app.agent.remediation import RemediationSession
from app.agent.schemas import RollbackProposal
from app.tools.recovery import get_simulated_recovery_window


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan")])
def test_invalid_error_rate_is_rejected(value):
    with pytest.raises(ValidationError):
        ErrorRateSample(
            service="checkout-service",
            metric="error_rate",
            timestamp="2026-09-28T14:11:00Z",
            value=value,
        )


def test_sample_requires_timezone():
    with pytest.raises(ValidationError):
        ErrorRateSample(
            service="checkout-service",
            metric="error_rate",
            timestamp="2026-09-28T14:11:00",
            value=0.01,
        )


def test_observation_cannot_precede_action():
    with pytest.raises(ValidationError, match="cannot precede"):
        RecoveryWindow(
            service="checkout-service",
            action_completed_at="2026-09-28T14:10:00Z",
            observed_at="2026-09-28T14:09:00Z",
            samples=[],
        )


def test_empty_recovery_window_is_valid():
    window = RecoveryWindow(
        service="checkout-service",
        action_completed_at="2026-09-28T14:10:00Z",
        observed_at="2026-09-28T14:13:00Z",
        samples=[],
    )

    assert window.samples == []


def sample_at(timestamp, value=0.01, service="checkout-service"):
    return {
        "service": service,
        "metric": "error_rate",
        "timestamp": timestamp,
        "value": value,
    }


def make_window(samples):
    return RecoveryWindow(
        service="checkout-service",
        action_completed_at="2026-09-28T14:10:00Z",
        observed_at="2026-09-28T14:15:00Z",
        samples=samples,
    )


@pytest.mark.parametrize("values, expected", [
    ([0.01, 0.02, 0.01], "recovered"),
    ([0.01, 0.03, 0.01], "not_recovered"),
    ([0.01, 0.01], "inconclusive"),
    ([], "inconclusive"),
])
def test_recovery_outcomes(values, expected):
    samples = [
        sample_at(f"2026-09-28T14:{11 + index:02d}:00Z", value)
        for index, value in enumerate(values)
    ]

    result = verify_recovery(make_window(samples))

    assert result["status"] == expected
    assert len(result["evaluated_samples"]) == len(values)


def test_unrelated_and_out_of_window_samples_are_excluded():
    result = verify_recovery(make_window([
        sample_at("2026-09-28T14:09:00Z"),
        sample_at("2026-09-28T14:10:00Z"),
        sample_at("2026-09-28T14:16:00Z"),
        sample_at("2026-09-28T14:12:00Z", service="payment-service"),
    ]))

    assert result["status"] == "inconclusive"
    assert result["evaluated_samples"] == []


def test_duplicate_timestamps_do_not_satisfy_sample_count():
    result = verify_recovery(make_window([
        sample_at("2026-09-28T14:11:00Z"),
        sample_at("2026-09-28T14:11:00Z"),
        sample_at("2026-09-28T14:11:00Z"),
    ]))

    assert result["status"] == "inconclusive"
    assert len(result["evaluated_samples"]) == 1


def test_conflicting_duplicates_keep_higher_error_rate():
    result = verify_recovery(make_window([
        sample_at("2026-09-28T14:11:00Z", 0.4),
        sample_at("2026-09-28T14:11:00Z", 0.01),
        sample_at("2026-09-28T14:12:00Z"),
        sample_at("2026-09-28T14:13:00Z"),
    ]))

    assert result["status"] == "not_recovered"
    assert result["evaluated_samples"][0]["value"] == 0.4


def test_latest_three_samples_are_used_regardless_of_input_order():
    result = verify_recovery(make_window([
        sample_at("2026-09-28T14:15:00Z"),
        sample_at("2026-09-28T14:11:00Z", 0.4),
        sample_at("2026-09-28T14:13:00Z"),
        sample_at("2026-09-28T14:14:00Z"),
    ]))

    assert result["status"] == "recovered"
    assert len(result["evaluated_samples"]) == 3
    assert all(
        sample["value"] == 0.01
        for sample in result["evaluated_samples"]
    )


@pytest.mark.parametrize("overrides", [
    {"service": "payment-service"},
    {"previous_version": "1.7.5"},
    {"current_version": "1.7.2"},
])
def test_recovery_rejects_mismatched_execution(overrides):
    remediation = {
        "status": "simulated",
        "service": "checkout-service",
        "previous_version": "1.7.4",
        "current_version": "1.7.3",
    }
    remediation.update(overrides)

    with pytest.raises(ValueError, match="does not match"):
        get_simulated_recovery_window(remediation)


def test_declined_remediation_does_not_load_recovery_data(monkeypatch):
    def unexpected_load(remediation):
        pytest.fail("Declined remediation must not load recovery observations.")

    monkeypatch.setattr(
        verification,
        "get_simulated_recovery_window",
        unexpected_load,
    )

    assert verification.verify_simulated_remediation({
        "status": "declined",
    }) is None


def test_approved_execution_can_be_verified():
    state = {
        "service": "checkout-service",
        "version": "1.7.4",
        "rollback_target_version": "1.7.3",
    }
    proposal = RollbackProposal(
        action="rollback_service",
        service="checkout-service",
        current_version="1.7.4",
        target_version="1.7.3",
        reason="Review the suspected regression.",
        evidence_ids=["evidence-001"],
    )

    session = RemediationSession()
    proposal_id = session.submit(
        proposal,
        state,
        [{"evidence_id": "evidence-001"}],
    )
    session.approve(proposal_id)

    remediation = session.execute(proposal_id, state)
    result = verification.verify_simulated_remediation(remediation)

    assert result["mode"] == "simulation"
    assert result["status"] == "recovered"
    assert len(result["evaluated_samples"]) == 3
