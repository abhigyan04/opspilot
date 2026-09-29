import json
from pathlib import Path

DATA_PATH = Path("data/scenarios/checkout_regression/deployments.json")

def get_deployments(service: str) -> list[dict]:
    with open(DATA_PATH, "r") as f:
        deployments = json.load(f)
    
    return [
        deployment
        for deployment in deployments
        if deployment["service"] == service
    ]
