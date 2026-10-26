import argparse
import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agent.settings import DiagnosisSettings
from app.agent.workflow import build_investigation_graph
from app.mcp_server.server import SUPPORTED_SCENARIOS
from app.tools.data import SCENARIOS_ROOT


async def start_workflow(*, database: Path, thread_id: str, incident: str, scenario: str, model: str, tool_backend: str) -> dict:
    if not thread_id.strip():
        raise ValueError("A nonblank thread ID is required.")
    if not incident.strip():
        raise ValueError("A nonblank incident is required.")
    if scenario not in SUPPORTED_SCENARIOS:
        raise ValueError(f"Unsupported scenario: {scenario}")
    if not model.strip():
        raise ValueError("A nonblank model is required.")
    if tool_backend not in {"direct", "mcp"}:
        raise ValueError("tool_backend must be 'direct' or 'mcp'")

    database = database.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
        if await saver.aget_tuple(config) is not None:
            raise ValueError(
                f"Thread {thread_id!r} already exists. "
                "Use a new thread ID or resume the existing workflow."
            )

        graph = build_investigation_graph(
            data_dir=SCENARIOS_ROOT / scenario,
            diagnosis_model=model,
            diagnosis_settings=DiagnosisSettings(
                num_ctx=8192,
                num_predict=2048,
            ),
            tool_backend=tool_backend,
            checkpointer=saver,
        )
        result = await graph.ainvoke(
            {"incident": incident},
            config=config,
        )
        saved = await graph.aget_state(config)

        return {
            "database": str(database),
            "thread_id": thread_id,
            "next": list(saved.next),
            "state": saved.values,
            "interrupts": [
                item.value for item in result.get("__interrupt__", ())
            ],
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Start a persistent OpsPilot investigation."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--database", type=Path, required=True)
    start.add_argument("--thread-id", required=True)
    start.add_argument("--incident", required=True)
    start.add_argument(
        "--scenario",
        choices=SUPPORTED_SCENARIOS,
        default="checkout_regression",
    )
    start.add_argument("--model", default="qwen3:8b")
    start.add_argument(
        "--tool-backend",
        choices=("direct", "mcp"),
        default="direct",
    )

    args = parser.parse_args(argv)
    result = asyncio.run(
        start_workflow(
            database=args.database,
            thread_id=args.thread_id,
            incident=args.incident,
            scenario=args.scenario,
            model=args.model,
            tool_backend=args.tool_backend,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
