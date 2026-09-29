import json
from pathlib import Path

DATA_PATH = Path("data/scenarios/checkout_regression/log.json")

def search_logs(service: str, level: str) -> list[dict]:
    with open(DATA_PATH, "r") as f:
        logs = json.load(f)
    
    return [
        log
        for log in logs
        if log["service"] == service and log["level"] == level
    ]
