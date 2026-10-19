from app.agent.remediation import RemediationSession
from evals.safety import (
    evaluate_approval_controls,
    evaluate_execution_guards,
)
import evals.safety as safety


def checks_by_id(report):
    return {
        check["check_id"]: check
        for check in report["checks"]
    }


def test_approval_controls_pass():
    report = evaluate_approval_controls()

    assert report["evaluation_mode"] == "simulation_safety"
    assert report["total_checks"] == 2
    assert report["passed_checks"] == 2

    checks = checks_by_id(report)
    assert checks["unapproved_execution_blocked"]["state_unchanged"]
    assert not checks["approved_execution"]["state_unchanged"]


def test_detects_approval_bypass(monkeypatch):
    original_execute = RemediationSession.execute

    def bypass_approval(self, proposal_id, current_state):
        self.approve(proposal_id)
        return original_execute(self, proposal_id, current_state)

    monkeypatch.setattr(
        RemediationSession, "execute", bypass_approval
    )

    checks = checks_by_id(evaluate_approval_controls())

    assert not checks["unapproved_execution_blocked"]["passed"]
    assert checks["approved_execution"]["passed"]


def test_rejecting_every_execution_does_not_pass(monkeypatch):
    def reject(self, proposal_id, current_state):
        raise ValueError("Proposal requires explicit approval.")

    monkeypatch.setattr(RemediationSession, "execute", reject)

    checks = checks_by_id(evaluate_approval_controls())

    assert checks["unapproved_execution_blocked"]["passed"]
    assert not checks["approved_execution"]["passed"]


def test_unexpected_errors_do_not_count_as_safe(monkeypatch):
    def crash(self, proposal_id, current_state):
        raise RuntimeError("Simulator failed")

    monkeypatch.setattr(RemediationSession, "execute", crash)

    report = evaluate_approval_controls()

    assert report["passed_checks"] == 0
    assert all(
        check["observed"] == "unexpected_error"
        for check in report["checks"]
    )


def test_execution_guards_pass():
    report = evaluate_execution_guards()

    assert report["total_checks"] == 3
    assert report["passed_checks"] == 3
    assert all(
        check["state_unchanged"]
        for check in report["checks"]
    )


def test_detects_stale_state_execution(monkeypatch):
    original_execute = RemediationSession.execute

    def ignore_state_changes(self, proposal_id, current_state):
        proposal = self.get_proposal(proposal_id)
        current_state["version"] = proposal.current_version
        current_state["rollback_target_version"] = proposal.target_version
        return original_execute(self, proposal_id, current_state)

    monkeypatch.setattr(
        RemediationSession, "execute", ignore_state_changes
    )

    checks = checks_by_id(evaluate_execution_guards())

    assert not checks["version_changed"]["passed"]
    assert not checks["rollback_target_changed"]["passed"]


def test_detects_duplicate_execution_bypass(monkeypatch):
    original_execute = RemediationSession.execute

    def allow_duplicate(self, proposal_id, current_state):
        if proposal_id in self._executed:
            return {"status": "simulated"}
        return original_execute(self, proposal_id, current_state)

    monkeypatch.setattr(
        RemediationSession, "execute", allow_duplicate
    )

    checks = checks_by_id(evaluate_execution_guards())

    assert not checks["duplicate_execution"]["passed"]
    assert checks["version_changed"]["passed"]
    assert checks["rollback_target_changed"]["passed"]


def test_recovery_outcomes_pass():
    report = safety.evaluate_recovery_outcomes()

    assert report["total_checks"] == 3
    assert report["passed_checks"] == 3

    checks = checks_by_id(report)
    assert checks["healthy_samples"]["observed"] == "recovered"
    assert checks["unhealthy_sample"]["observed"] == "not_recovered"
    assert checks["insufficient_samples"]["observed"] == "inconclusive"


def test_detects_verifier_that_always_reports_recovery(monkeypatch):
    monkeypatch.setattr(
        safety,
        "verify_recovery",
        lambda window: {"status": "recovered"},
    )

    report = safety.evaluate_recovery_outcomes()
    checks = checks_by_id(report)

    assert report["passed_checks"] == 1
    assert not checks["unhealthy_sample"]["passed"]
    assert not checks["insufficient_samples"]["passed"]


def test_recovery_errors_do_not_pass(monkeypatch):
    def crash(window):
        raise RuntimeError("Verification failed")

    monkeypatch.setattr(safety, "verify_recovery", crash)

    report = safety.evaluate_recovery_outcomes()

    assert report["passed_checks"] == 0
    assert all(check["error"] for check in report["checks"])


def test_combined_simulation_controls():
    report = safety.evaluate_simulation_controls()

    assert report["total_checks"] == 10
    assert report["passed_checks"] == 10
    assert set(report["sections"]) == {
        "approval",
        "execution_guards",
        "recovery",
        "review_workflow"
    }


def test_review_workflow_passes():
    report = safety.evaluate_review_workflow()
    checks = checks_by_id(report)

    assert report["total_checks"] == 2
    assert report["passed_checks"] == 2
    assert checks["declined_without_recovery"]["recovery"] is None
    assert checks["declined_without_recovery"]["state_unchanged"]
    assert (
        checks["approved_execution_recovery"]["recovery"]["status"]
        == "recovered"
    )


def test_decline_never_executes(monkeypatch):
    original_execute = RemediationSession.execute
    executions = []

    def record_execution(self, proposal_id, current_state):
        executions.append(proposal_id)
        return original_execute(self, proposal_id, current_state)

    monkeypatch.setattr(
        RemediationSession, "execute", record_execution
    )

    report = safety.evaluate_review_workflow()
    checks = checks_by_id(report)

    assert report["passed_checks"] == 2
    assert executions == [
        checks["approved_execution_recovery"]["execution"]["proposal_id"]
    ]


def test_execution_without_recovery_does_not_pass(monkeypatch):
    monkeypatch.setattr(
        safety,
        "verify_simulated_remediation",
        lambda execution: None,
    )

    checks = checks_by_id(safety.evaluate_review_workflow())

    assert checks["declined_without_recovery"]["passed"]
    assert not checks["approved_execution_recovery"]["passed"]


def test_wrong_execution_cannot_use_recovery_fixture(monkeypatch):
    original_review = safety.review_and_execute

    def wrong_version(*args, **kwargs):
        result = original_review(*args, **kwargs)
        if result["status"] == "simulated":
            result["current_version"] = "1.7.2"
        return result

    monkeypatch.setattr(safety, "review_and_execute", wrong_version)

    checks = checks_by_id(safety.evaluate_review_workflow())
    approved = checks["approved_execution_recovery"]

    assert not approved["passed"]
    assert approved["recovery"] is None
    assert "does not match the recovery scenario" in approved["error"]
