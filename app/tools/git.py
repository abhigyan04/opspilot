import json
from pathlib import Path

DATA_PATH = Path("data/scenarios/checkout_regression/commits.json")

def get_commit(commit_hash: str) -> dict | None:
    with open(DATA_PATH, "r") as f:
        commits = json.load(f)
    
    return next(
        (commit for commit in commits if commit["hash"] == commit_hash),
        None
    )
