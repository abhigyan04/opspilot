from pathlib import Path

from app.tools.data import DEFAULT_SCENARIO_DIR, read_fixture


def search_logs(service: str, level: str, *, data_dir: Path = DEFAULT_SCENARIO_DIR) -> list[dict]:
    logs = read_fixture("log.json", data_dir)

    return [
        log
        for log in logs
        if log["service"] == service and log["level"] == level
    ]
