from fastapi import FastAPI


def create_app() -> FastAPI:
    application = FastAPI(
        title="OpsPilot",
        version="0.1.0",
        description="Local incident investigation and review.",
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
