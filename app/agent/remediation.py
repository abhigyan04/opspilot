from app.agent.schemas import RollbackProposal, Diagnosis
from uuid import uuid4
import json


def validate_rollback_target(proposal: RollbackProposal, deployment: dict) -> None:
    if proposal.service != deployment["service"]:
        raise ValueError("Proposal service does not match deployment.")

    if proposal.current_version != deployment["version"]:
        raise ValueError("Proposal current version does not match deployment.")

    if proposal.target_version == proposal.current_version:
        raise ValueError("Rollback target must differ from current version.")

    allowed_target = deployment.get("rollback_target_version")

    if allowed_target is None or proposal.target_version != allowed_target:
        raise ValueError("Rollback target is not available for this deployment.")


def validate_rollback_evidence(proposal: RollbackProposal, steps: list[dict]) -> None:
    known_ids = {step["evidence_id"] for step in steps}
    unknown_ids = set(proposal.evidence_ids) - known_ids

    if unknown_ids:
        raise ValueError(f"Rollback proposal cites unknown evidence IDs: {sorted(unknown_ids)}")


def build_rollback_proposal(diagnosis: Diagnosis, service: str, steps: list[dict]) -> RollbackProposal | None:
    if diagnosis.status != "supported":
        return None

    candidates = [
        (step["evidence_id"], deployment)
        for step in steps
        if step["decision"]["tool"] == "get_deployments"
        for deployment in step["result"]
        if deployment["service"] == service
    ]

    # Avoid choosing between ambiguous deployment records.
    if len(candidates) != 1:
        return None

    deployment_evidence_id, deployment = candidates[0]
    target = deployment.get("rollback_target_version")

    if not target:
        return None

    evidence_ids = list(dict.fromkeys([
        *diagnosis.root_cause.evidence_ids,
        deployment_evidence_id,
    ]))

    proposal = RollbackProposal(
        action="rollback_service",
        service=service,
        current_version=deployment["version"],
        target_version=target,
        reason=(
            "Rollback candidate for human review. "
            f"Diagnosis: {diagnosis.root_cause.statement}"
        ),
        evidence_ids=evidence_ids,
    )

    validate_rollback_target(proposal, deployment)
    validate_rollback_evidence(proposal, steps)
    return proposal


def review_and_execute(proposal: RollbackProposal, steps: list[dict], current_state: dict, input_fn=input, output_fn=print) -> dict:
    session = RemediationSession()
    proposal_id = session.submit(proposal, current_state, steps)

    output_fn(json.dumps({
        "proposal_id": proposal_id,
        "proposal": session.get_proposal(proposal_id).model_dump(),
    }, indent=2))

    output_fn(
        "Simulation only. Review the diagnosis, limitations, and proposal. "
        "Execution changes in-memory state; it does not verify recovery."
    )

    try:
        answer = input_fn(
            f"Type 'approve {proposal_id}' to execute, "
            "or press Enter to decline: "
        )
    except (EOFError, KeyboardInterrupt):
        return {"status": "declined", "proposal_id": proposal_id}

    if answer.strip() != f"approve {proposal_id}":
        return {"status": "declined", "proposal_id": proposal_id}

    session.approve(proposal_id)
    return session.execute(proposal_id, current_state)


class RemediationSession:
    def __init__(self):
        self._proposals: dict[str, str] = {}
        self._approved: set[str] = set()
        self._executed: set[str] = set()

    def submit(
        self,
        proposal: RollbackProposal,
        deployment: dict,
        steps: list[dict],
    ) -> str:
        validate_rollback_target(proposal, deployment)
        validate_rollback_evidence(proposal, steps)

        proposal_id = str(uuid4())
        self._proposals[proposal_id] = proposal.model_dump_json()
        return proposal_id

    def get_proposal(self, proposal_id: str) -> RollbackProposal:
        if proposal_id not in self._proposals:
            raise ValueError("Unknown proposal ID.")

        return RollbackProposal.model_validate_json(
            self._proposals[proposal_id]
        )

    def approve(self, proposal_id: str) -> None:
        self.get_proposal(proposal_id)
        self._approved.add(proposal_id)

    def is_approved(self, proposal_id: str) -> bool:
        self.get_proposal(proposal_id)
        return proposal_id in self._approved
    
    def execute(self, proposal_id: str, current_state: dict) -> dict:
        proposal = self.get_proposal(proposal_id)

        if proposal_id in self._executed:
            raise ValueError("Proposal has already been executed.")

        if proposal_id not in self._approved:
            raise ValueError("Proposal requires explicit approval.")

        # Recheck at execution time: state may have changed since submission.
        validate_rollback_target(proposal, current_state)

        previous_version = current_state["version"]
        current_state["version"] = proposal.target_version

        # The old rollback target no longer describes an available next action.
        current_state["rollback_target_version"] = None

        self._executed.add(proposal_id)
        self._approved.remove(proposal_id)

        return {
            "status": "simulated",
            "proposal_id": proposal_id,
            "service": proposal.service,
            "previous_version": previous_version,
            "current_version": current_state["version"]
        }
