import argparse
import asyncio
import json
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agent.settings import DiagnosisSettings
from app.agent.workflow import build_investigation_graph
from app.mcp_server.server import SUPPORTED_SCENARIOS
from app.tools.data import SCENARIOS_ROOT


class WorkflowNotFoundError(ValueError):
    pass


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


async def inspect_workflow(*, database: Path, thread_id: str) -> dict:
    if not thread_id.strip():
        raise ValueError("A nonblank thread ID is required.")

    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Checkpoint database does not exist: {database}")

    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
        if await saver.aget_tuple(config) is None:
            raise WorkflowNotFoundError(f"Thread {thread_id!r} does not exist.")

        # Compile the graph only to interpret its saved state.
        # Do not invoke it or apply new configuration to the checkpoint.
        graph = build_investigation_graph(checkpointer=saver)
        saved = await graph.aget_state(config)

        return {
            "database": str(database),
            "thread_id": thread_id,
            "next": list(saved.next),
            "state": saved.values,
            "interrupts": [item.value for item in saved.interrupts],
        }


async def resume_workflow(*, database: Path, thread_id: str, response: str | None = None, retry: bool = False) -> dict:
    if not thread_id.strip():
        raise ValueError("A nonblank thread ID is required.")

    if retry:
        if response is not None:
            raise ValueError("Choose either retry or a review response.")
    elif not isinstance(response, str) or not response.strip():
        raise ValueError("An explicit review response is required.")

    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(
            f"Checkpoint database does not exist: {database}"
        )

    config = {"configurable": {"thread_id": thread_id}}

    async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
        checkpoint = await saver.aget_tuple(config)
        if checkpoint is None:
            raise ValueError(f"Thread {thread_id!r} does not exist.")

        saved_config = checkpoint.checkpoint["channel_values"].get(
            "workflow_config"
        )
        expected_keys = {
            "version",
            "data_dir",
            "tool_backend",
            "max_steps",
            "diagnosis_model",
            "diagnosis_settings",
            "service",
        }
        if (
            not isinstance(saved_config, dict)
            or set(saved_config) != expected_keys
            or saved_config["version"] != 4
        ):
            raise ValueError(
                "Unsupported or missing saved workflow configuration."
            )

        graph = build_investigation_graph(
            data_dir=Path(saved_config["data_dir"]),
            max_steps=saved_config["max_steps"],
            diagnosis_model=saved_config["diagnosis_model"],
            diagnosis_settings=DiagnosisSettings.model_validate(
                saved_config["diagnosis_settings"]
            ),
            tool_backend=saved_config["tool_backend"],
            service=saved_config["service"],
            checkpointer=saver,
        )
        pending = await graph.aget_state(config)

        if not pending.next:
            raise ValueError("Workflow is already complete.")

        if retry:
            if pending.interrupts:
                raise ValueError(
                    "Workflow is waiting for review; provide a review response."
                )

            retryable = pending.next in {
                ("investigate",),
                ("diagnose",),
            }
            has_recorded_failure = any(
                task.name in pending.next and task.error is not None
                for task in pending.tasks
            )
            if not retryable or not has_recorded_failure:
                raise ValueError(
                    "Workflow has no recorded investigation or diagnosis "
                    "failure to retry."
                )

            await graph.ainvoke(None, config=config)
        else:
            if pending.next != ("review",) or not pending.interrupts:
                raise ValueError(
                    "Workflow is not waiting for a review response."
                )

            await graph.ainvoke(
                Command(resume=response),
                config=config,
            )
        saved = await graph.aget_state(config)

        return {
            "database": str(database),
            "thread_id": thread_id,
            "next": list(saved.next),
            "state": saved.values,
            "interrupts": [item.value for item in saved.interrupts],
        }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Start, inspect, and review persistent OpsPilot workflows."
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
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--database", type=Path, required=True)
    inspect.add_argument("--thread-id", required=True)

    resume = commands.add_parser("resume")
    resume.add_argument("--database", type=Path, required=True)
    resume.add_argument("--thread-id", required=True)
    resume_action = resume.add_mutually_exclusive_group(required=True)
    resume_action.add_argument("--response")
    resume_action.add_argument("--retry", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "inspect":
        result = asyncio.run(
            inspect_workflow(
                database=args.database,
                thread_id=args.thread_id,
            )
        )
    elif args.command == "resume":
        result = asyncio.run(
            resume_workflow(
                database=args.database,
                thread_id=args.thread_id,
                response=args.response,
                retry=args.retry
            )
        )
    else:
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
