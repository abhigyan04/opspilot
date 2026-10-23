import asyncio
from pathlib import Path
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent import agent
from app.agent.settings import DiagnosisSettings
from app.agent.usage import UsageCollector
from app.tools.data import DEFAULT_SCENARIO_DIR, SCENARIOS_ROOT
from app.mcp_server.client import connect_local_tools
from app.mcp_server.server import SUPPORTED_SCENARIOS


class InvestigationState(TypedDict):
    incident: str
    investigation: NotRequired[dict]
    diagnosis: NotRequired[dict]
    usage: NotRequired[dict]


def build_investigation_graph(*, data_dir: Path = DEFAULT_SCENARIO_DIR, max_steps: int = 6, diagnosis_model: str = agent.DEFAULT_DIAGNOSIS_MODEL, diagnosis_settings: DiagnosisSettings | None = None, tool_backend: str = "direct"):
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    if not diagnosis_model.strip():
        raise ValueError("A nonblank diagnosis model is required.")

    if tool_backend not in {"direct", "mcp"}:
        raise ValueError("tool_backend must be 'direct' or 'mcp'")

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

    async def investigate_node(state: InvestigationState) -> dict:
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

    builder = StateGraph(InvestigationState)
    builder.add_node("investigate", investigate_node)
    builder.add_node("diagnose", diagnose_node)

    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "diagnose")
    builder.add_edge("diagnose", END)

    return builder.compile()
