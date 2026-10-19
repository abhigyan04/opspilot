import json
from copy import deepcopy

from app.agent.remediation import RemediationSession, review_and_execute
from app.agent.schemas import RollbackProposal, RecoveryWindow
from app.agent.verification import verify_recovery, verify_simulated_remediation


def evaluate_approval_controls() -> dict:
    checks = []

    for approved in (False, True):
        state = {
            "service": "checkout-service",
            "version": "1.7.4",
            "rollback_target_version": "1.7.3",
        }
        before = deepcopy(state)
        proposal = RollbackProposal(
            action="rollback_service",
            service="checkout-service",
            current_version="1.7.4",
            target_version="1.7.3",
            reason="Synthetic approval-control evaluation.",
            evidence_ids=["evidence-001"],
        )
        steps = [{
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "get_deployments",
                "arguments": {"service": "checkout-service"},
            },
            "result": [deepcopy(state)],
        }]

        session = RemediationSession()
        proposal_id = session.submit(proposal, state, steps)
        if approved:
            session.approve(proposal_id)

        result = None
        error = None
        observed = "returned"

        try:
            result = session.execute(proposal_id, state)
        except ValueError as exc:
            error = str(exc)
            observed = (
                "approval_required"
                if error == "Proposal requires explicit approval."
                else "unexpected_error"
            )
        except Exception as exc:
            observed = "unexpected_error"
            error = f"{type(exc).__name__}: {exc}"

        if approved:
            expected_state = {
                **before,
                "version": "1.7.3",
                "rollback_target_version": None,
            }
            expected_result = {
                "status": "simulated",
                "proposal_id": proposal_id,
                "service": "checkout-service",
                "previous_version": "1.7.4",
                "current_version": "1.7.3",
            }
            passed = (
                observed == "returned"
                and result == expected_result
                and state == expected_state
                and not session.is_approved(proposal_id)
            )
        else:
            passed = (
                observed == "approval_required"
                and state == before
            )

        checks.append({
            "check_id": (
                "approved_execution"
                if approved
                else "unapproved_execution_blocked"
            ),
            "passed": passed,
            "observed": observed,
            "state_unchanged": state == before,
            "error": error,
        })

    return {
        "evaluation_mode": "simulation_safety",
        "checks": checks,
        "total_checks": len(checks),
        "passed_checks": sum(check["passed"] for check in checks),
    }


def evaluate_execution_guards() -> dict:
    checks = []

    scenarios = (
        "version_changed",
        "rollback_target_changed",
        "duplicate_execution",
    )

    for scenario in scenarios:
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
            reason="Synthetic execution-guard evaluation.",
            evidence_ids=["evidence-001"],
        )
        steps = [{"evidence_id": "evidence-001"}]

        session = RemediationSession()
        proposal_id = session.submit(proposal, state, steps)
        session.approve(proposal_id)

        if scenario == "version_changed":
            state["version"] = "1.7.5"
        elif scenario == "rollback_target_changed":
            state["rollback_target_version"] = "1.7.2"
        else:
            session.execute(proposal_id, state)
            # Reapproval must not permit execution of a consumed proposal.
            session.approve(proposal_id)

        before = deepcopy(state)
        observed = "returned"
        error = None

        try:
            session.execute(proposal_id, state)
        except ValueError as exc:
            observed = "rejected"
            error = str(exc)
        except Exception as exc:
            observed = "unexpected_error"
            error = f"{type(exc).__name__}: {exc}"

        checks.append({
            "check_id": scenario,
            "passed": observed == "rejected" and state == before,
            "observed": observed,
            "state_unchanged": state == before,
            "error": error,
        })

    return {
        "evaluation_mode": "simulation_safety",
        "checks": checks,
        "total_checks": len(checks),
        "passed_checks": sum(check["passed"] for check in checks),
    }


def evaluate_recovery_outcomes() -> dict:
    scenarios = (
        ("healthy_samples", [0.01, 0.02, 0.01], "recovered"),
        ("unhealthy_sample", [0.01, 0.03, 0.01], "not_recovered"),
        ("insufficient_samples", [0.01, 0.01], "inconclusive"),
    )
    checks = []

    for check_id, values, expected in scenarios:
        window = RecoveryWindow(
            service="checkout-service",
            action_completed_at="2026-09-28T14:10:00Z",
            observed_at="2026-09-28T14:15:00Z",
            samples=[
                {
                    "service": "checkout-service",
                    "metric": "error_rate",
                    "timestamp": f"2026-09-28T14:{11 + index:02d}:00Z",
                    "value": value,
                }
                for index, value in enumerate(values)
            ],
        )

        observed = None
        error = None

        try:
            observed = verify_recovery(window)["status"]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        checks.append({
            "check_id": check_id,
            "expected": expected,
            "observed": observed,
            "passed": error is None and observed == expected,
            "error": error,
        })

    return {
        "evaluation_mode": "simulation_recovery",
        "checks": checks,
        "total_checks": len(checks),
        "passed_checks": sum(check["passed"] for check in checks),
    }


def evaluate_simulation_controls() -> dict:
    sections = {
        "approval": evaluate_approval_controls(),
        "execution_guards": evaluate_execution_guards(),
        "recovery": evaluate_recovery_outcomes(),
        "review_workflow": evaluate_review_workflow()
    }

    return {
        "evaluation_mode": "simulation_controls",
        "sections": sections,
        "total_checks": sum(
            section["total_checks"] for section in sections.values()
        ),
        "passed_checks": sum(
            section["passed_checks"] for section in sections.values()
        ),
    }


def evaluate_review_workflow() -> dict:
    checks = []

    for approve in (False, True):
        state = {
            "service": "checkout-service",
            "version": "1.7.4",
            "rollback_target_version": "1.7.3",
        }
        before = deepcopy(state)
        proposal = RollbackProposal(
            action="rollback_service",
            service="checkout-service",
            current_version="1.7.4",
            target_version="1.7.3",
            reason="Synthetic review-workflow evaluation.",
            evidence_ids=["evidence-001"],
        )
        steps = [{"evidence_id": "evidence-001"}]
        output = []
        execution = None
        recovery = None
        error = None
        prompts = []

        def answer(prompt):
            prompts.append(prompt)
            displayed = json.loads(output[0])
            return (
                f"approve {displayed['proposal_id']}"
                if approve
                else ""
            )

        try:
            execution = review_and_execute(
                proposal,
                steps,
                state,
                input_fn=answer,
                output_fn=output.append,
            )
            recovery = verify_simulated_remediation(execution)

            if approve:
                passed = (
                    len(prompts) == 1
                    and execution["status"] == "simulated"
                    and execution["service"] == "checkout-service"
                    and execution["previous_version"] == "1.7.4"
                    and execution["current_version"] == "1.7.3"
                    and state == {
                        **before,
                        "version": "1.7.3",
                        "rollback_target_version": None,
                    }
                    and recovery is not None
                    and recovery["mode"] == "simulation"
                    and recovery["status"] == "recovered"
                )
            else:
                passed = (
                    len(prompts) == 1
                    and execution["status"] == "declined"
                    and state == before
                    and recovery is None
                )
        except Exception as exc:
            passed = False
            error = f"{type(exc).__name__}: {exc}"

        checks.append({
            "check_id": (
                "approved_execution_recovery"
                if approve
                else "declined_without_recovery"
            ),
            "passed": passed,
            "execution": execution,
            "recovery": recovery,
            "state_unchanged": state == before,
            "error": error,
        })

    return {
        "evaluation_mode": "simulation_review_workflow",
        "checks": checks,
        "total_checks": len(checks),
        "passed_checks": sum(check["passed"] for check in checks),
    }
