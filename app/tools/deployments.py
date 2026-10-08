from pathlib import Path

from app.tools.data import DEFAULT_SCENARIO_DIR, read_fixture


def get_deployments(service: str, *, data_dir: Path = DEFAULT_SCENARIO_DIR) -> list[dict]:
    deployments = read_fixture("deployments.json", data_dir)

    return [
        deployment
        for deployment in deployments
        if deployment["service"] == service
    ]
