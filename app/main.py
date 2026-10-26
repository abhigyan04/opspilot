from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.agent.workflow_cli import (
    WorkflowNotFoundError,
    inspect_workflow,
)


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

    return application


app = create_app()
