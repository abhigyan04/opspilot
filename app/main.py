from pathlib import Path
import logging
from uuid import uuid4
import asyncio

from fastapi import Response
from fastapi.responses import FileResponse

from app.api.schemas import StartWorkflowRequest, ReviewWorkflowRequest
from fastapi import FastAPI, HTTPException

from app.agent.workflow_cli import (
    WorkflowNotFoundError,
    inspect_workflow,
    start_workflow,
    resume_workflow
)


logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_DATABASE = (
    Path(__file__).resolve().parents[1]
    / "out"
    / "workflows"
    / "checkpoints.sqlite"
)

DEMO_FILES = {
    "checkout_regression":
        Path(__file__).resolve().parent / "web" / "demo-data" / "checkout_regression.json",
    "payment_provider_outage":
        Path(__file__).resolve().parent / "web" / "demo-data" / "payment_provider_outage.json",
}

def create_app(*, database: Path = DEFAULT_WORKFLOW_DATABASE) -> FastAPI:
    database = database.resolve()
    review_lock = asyncio.Lock()

    application = FastAPI(
        title="OpsPilot",
        version="0.1.0",
        description="Local incident investigation and review.",
    )

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "web" / "index.html",
            media_type="text/html",
        )

    @application.get("/demo.html", include_in_schema=False)
    async def demo_page() -> FileResponse:
        return FileResponse(
            Path(__file__).resolve().parent / "web" / "demo.html",
            media_type="text/html",
        )

    @application.get("/demo-data/{scenario}.json", include_in_schema=False)
    async def get_demo_data(scenario: str) -> FileResponse:
        path = DEMO_FILES.get(scenario)
        if path is None:
            raise HTTPException(
                status_code=404,
                detail="Demo scenario not found.",
            )

        return FileResponse(path, media_type="application/json")

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

    @application.post("/workflows/{thread_id}/review")
    async def review_workflow(thread_id: str, request: ReviewWorkflowRequest) -> dict:
        if not thread_id.strip():
            raise HTTPException(
                status_code=422,
                detail="A nonblank thread ID is required.",
            )

        async with review_lock:
            try:
                pending = await inspect_workflow(
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

            state = pending["state"]
            if (
                pending["next"] != ["review"]
                or not pending["interrupts"]
                or state.get("proposal_status") != "review_required"
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Workflow is not waiting for review.",
                )

            if state.get("proposal_id") != request.proposal_id:
                raise HTTPException(
                    status_code=409,
                    detail="Proposal ID does not match the pending proposal.",
                )

            try:
                result = await resume_workflow(
                    database=database,
                    thread_id=thread_id,
                    response=f"{request.decision} {request.proposal_id}",
                )
            except ValueError:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Saved workflow cannot accept this review. "
                        "Inspect its current state."
                    ),
                ) from None
            except Exception:
                logger.exception("Workflow review failed: %s", thread_id)
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Workflow review failed. "
                        "Inspect its current state before retrying."
                    ),
                ) from None

            return {
                "thread_id": result["thread_id"],
                "next": result["next"],
                "state": result["state"],
                "interrupts": result["interrupts"],
            }

    return application


app = create_app()
