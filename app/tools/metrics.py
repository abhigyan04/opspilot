import json
from pathlib import Path

DATA_PATH = Path("data/scenarios/checkout_regression/metrics.json")

def query_metrics(service: str, metric_name: str) -> list[dict]:
    with open(DATA_PATH, "r") as f:
        metrics = json.load(f)
    
    return [
        metric
        for metric in metrics
        if metric["service"] == service and metric["metric"] == metric_name
    ]
