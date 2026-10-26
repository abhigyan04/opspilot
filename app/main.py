from pathlib import Path
import logging
from uuid import uuid4

from fastapi import Response

from app.api.schemas import StartWorkflowRequest
from fastapi import FastAPI, HTTPException

from app.agent.workflow_cli import (
    WorkflowNotFoundError,
    inspect_workflow,
    start_workflow
)


logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_DATABASE = (
    Path(__file__).resolve().parents[1]
    / "out"
    / "workflows"
    / "checkpoints.sqlite"
)


def create_app(*, database: Path = DEFAULT_WORKFLOW_DATABASE) -> FastAPI:
    database = database.resolve()

    application = FastAPI(
        title="OpsPilot",
        version="0.1.0",
        description="Local incident investigation and review.",
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/workflows/{thread_id}")
    async def get_workflow(thread_id: str) -> dict:
        if not thread_id.strip():
            raise HTTPException(
                status_code=422,
                detail="A nonblank thread ID is required.",
            )

        try:
            result = await inspect_workflow(
                database=database,
                thread_id=thread_id,
            )
        except WorkflowNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="Workflow not found.",
            ) from None
        except FileNotFoundError:
            raise HTTPException(
                status_code=503,
                detail="Workflow database is unavailable.",
            ) from None

        return {
            "thread_id": result["thread_id"],
            "next": result["next"],
            "state": result["state"],
            "interrupts": result["interrupts"],
        }

    @application.post(
        "/workflows",
        status_code=201,
        responses={
            500: {"description": "Workflow execution failed."},
        },
    )
    async def post_workflow(request: StartWorkflowRequest, response: Response) -> dict:
        thread_id = f"workflow-{uuid4()}"

        try:
            result = await start_workflow(
                database=database,
                thread_id=thread_id,
                incident=request.incident,
                scenario=request.scenario,
                model="qwen3:8b",
                tool_backend=request.tool_backend,
            )
        except Exception:
            logger.exception("Workflow start failed: %s", thread_id)
            raise HTTPException(
                status_code=500,
                detail={
                    "message": (
                        "Workflow execution failed. "
                        "Inspect this thread for any saved checkpoint."
                    ),
                    "thread_id": thread_id,
                },
            ) from None

        response.headers["Location"] = f"/workflows/{thread_id}"
        return {
            "thread_id": result["thread_id"],
            "next": result["next"],
            "state": result["state"],
            "interrupts": result["interrupts"],
        }

    return application


app = create_app()
