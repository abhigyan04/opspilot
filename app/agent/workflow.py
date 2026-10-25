import asyncio
from pathlib import Path
from typing import NotRequired, TypedDict
from copy import deepcopy
from uuid import uuid4

from langgraph.types import interrupt
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent import agent
from app.agent.settings import DiagnosisSettings
from app.agent.usage import UsageCollector
from app.tools.data import DEFAULT_SCENARIO_DIR, SCENARIOS_ROOT
from app.mcp_server.client import connect_local_tools
from app.mcp_server.server import SUPPORTED_SCENARIOS
from app.agent.schemas import diagnosis_adapter
from app.agent.remediation import build_rollback_proposal


class InvestigationState(TypedDict):
    incident: str
    investigation: NotRequired[dict]
    diagnosis: NotRequired[dict]
    usage: NotRequired[dict]
    workflow_config: NotRequired[dict]
    proposal: NotRequired[dict | None]
    proposal_status: NotRequired[str]
    proposal_id: NotRequired[str | None]


def build_investigation_graph(*, data_dir: Path = DEFAULT_SCENARIO_DIR, max_steps: int = 6,
                              diagnosis_model: str = agent.DEFAULT_DIAGNOSIS_MODEL,
                              diagnosis_settings: DiagnosisSettings | None = None, tool_backend: str = "direct",
                              checkpointer: BaseCheckpointSaver | None = None, service: str = "checkout-service"):
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    if not diagnosis_model.strip():
        raise ValueError("A nonblank diagnosis model is required.")

    if tool_backend not in {"direct", "mcp"}:
        raise ValueError("tool_backend must be 'direct' or 'mcp'")

    if not isinstance(service, str) or not service.strip():
        raise ValueError("A nonblank service is required.")

    scenario = data_dir.name
    if tool_backend == "mcp":
        if scenario not in SUPPORTED_SCENARIOS:
            raise ValueError(f"Unsupported MCP scenario: {scenario}")

        if data_dir.resolve() != (SCENARIOS_ROOT / scenario).resolve():
            raise ValueError(
                "MCP requires the standard fixture directory for the selected scenario."
            )

    settings = (
        diagnosis_settings
        if diagnosis_settings is not None
        else DiagnosisSettings()
    )
    
    workflow_config = {
        "version": 3,
        "data_dir": str(data_dir.resolve()),
        "tool_backend": tool_backend,
        "max_steps": max_steps,
        "diagnosis_model": diagnosis_model,
        "diagnosis_settings": settings.model_dump(mode="json"),
        "service": service
    }

    def require_matching_config(state: InvestigationState) -> None:
        if state.get("workflow_config") != workflow_config:
            raise ValueError(
                "Workflow configuration does not match the saved checkpoint. "
                "Resume with the original configuration or use a new thread."
            )

    def prepare_node(state: InvestigationState) -> dict:
        if "workflow_config" in state:
            require_matching_config(state)
        elif any(
            key in state for key in ("investigation", "diagnosis", "usage")
        ):
            raise ValueError(
                "Existing workflow state has no saved configuration."
            )

        return {"workflow_config": deepcopy(workflow_config)}

    async def investigate_node(state: InvestigationState) -> dict:
        require_matching_config(state)
        usage = UsageCollector()

        if tool_backend == "direct":
            investigation = await agent.investigate_async(
                state["incident"],
                max_steps=max_steps,
                data_dir=data_dir,
                usage=usage,
            )
        else:
            async with connect_local_tools(scenario=scenario) as executor:
                investigation = await agent.investigate_async(
                    state["incident"],
                    max_steps=max_steps,
                    usage=usage,
                    tool_executor=executor.execute,
                )

        return {
            "investigation": investigation,
            "usage": {"investigation": usage.snapshot()},
        }

    async def diagnose_node(state: InvestigationState) -> dict:
        require_matching_config(state)
        usage = UsageCollector()
        diagnosis = await asyncio.to_thread(
            agent.generate_diagnosis,
            state["incident"],
            state["investigation"]["steps"],
            model=diagnosis_model,
            settings=settings,
            usage=usage,
        )
        return {
            "diagnosis": diagnosis.model_dump(mode="json"),
            "usage": {
                **state["usage"],
                "diagnosis": usage.snapshot(),
            },
        }
    
    def propose_node(state: InvestigationState) -> dict:
        require_matching_config(state)

        diagnosis = diagnosis_adapter.validate_python(state["diagnosis"])
        proposal = build_rollback_proposal(
            diagnosis,
            service,
            state["investigation"]["steps"],
        )

        return {
            "proposal": (
                proposal.model_dump(mode="json")
                if proposal is not None
                else None
            ),
            "proposal_status": (
                "review_required" if proposal is not None else "no_proposal"
            ),
            "proposal_id": str(uuid4()) if proposal is not None else None
        }

    def route_proposal(state: InvestigationState) -> str:
        return "review" if state["proposal"] is not None else "done"

    def review_node(state: InvestigationState) -> dict:
        require_matching_config(state)

        if checkpointer is None:
            raise ValueError("Proposal review requires a checkpointer.")

        proposal_id = state["proposal_id"]
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError("Proposal review requires a saved proposal ID.")

        response = interrupt({
            "kind": "rollback_review",
            "proposal_id": proposal_id,
            "proposal": deepcopy(state["proposal"]),
            "diagnosis": deepcopy(state["diagnosis"]),
            "instructions": (
                f"Reply with 'approve {proposal_id}' or "
                f"'decline {proposal_id}'. "
                "This records review only; it does not execute a rollback."
            ),
        })

        if response == f"approve {proposal_id}":
            status = "approved"
        elif response == f"decline {proposal_id}":
            status = "declined"
        else:
            raise ValueError(
                "Review response must explicitly approve or decline "
                "the saved proposal ID."
            )

        return {"proposal_status": status}

    builder = StateGraph(InvestigationState)
    builder.add_node("investigate", investigate_node)
    builder.add_node("diagnose", diagnose_node)
    builder.add_node("prepare", prepare_node)
    builder.add_node("propose", propose_node)
    builder.add_node("review", review_node)

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "investigate")
    builder.add_edge("investigate", "diagnose")
    builder.add_edge("diagnose", "propose")
    builder.add_conditional_edges(
        "propose",
        route_proposal,
        {"review": "review", "done": END},
    )
    builder.add_edge("review", END)

    return builder.compile(checkpointer=checkpointer)
