import json
from pathlib import Path

from app.agent.schemas import RecoveryWindow


DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "data/scenarios/checkout_regression/recovery.json"
)


def get_simulated_recovery_window(remediation: dict) -> RecoveryWindow:
    if remediation.get("status") != "simulated":
        raise ValueError("Recovery observations require simulated execution.")

    with DATA_PATH.open(encoding="utf-8") as source:
        scenario = json.load(source)

    window = RecoveryWindow.model_validate(scenario["window"])

    if (
        remediation.get("service") != window.service
        or remediation.get("previous_version") != scenario["previous_version"]
        or remediation.get("current_version") != scenario["current_version"]
    ):
        raise ValueError("Remediation does not match the recovery scenario.")

    return window
