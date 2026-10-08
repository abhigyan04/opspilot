from pathlib import Path

from app.tools.data import DEFAULT_SCENARIO_DIR, read_fixture


def query_metrics(service: str, metric_name: str, *, data_dir: Path = DEFAULT_SCENARIO_DIR) -> list[dict]:
    metrics = read_fixture("metrics.json", data_dir)

    return [
        metric
        for metric in metrics
        if metric["service"] == service
        and metric["metric"] == metric_name
    ]
