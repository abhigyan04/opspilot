from app.agent.schemas import ErrorRateSample, RecoveryWindow
from app.tools.recovery import get_simulated_recovery_window


ERROR_RATE_THRESHOLD = 0.02
REQUIRED_SAMPLES = 3


def verify_recovery(window: RecoveryWindow) -> dict:
    by_timestamp: dict = {}

    for sample in window.samples:
        if sample.service != window.service:
            continue

        if not (
            window.action_completed_at
            < sample.timestamp
            <= window.observed_at
        ):
            continue

        previous: ErrorRateSample | None = by_timestamp.get(sample.timestamp)

        # Duplicate timestamps count once. Keep the higher error rate
        # if duplicate observations disagree.
        if previous is None or sample.value > previous.value:
            by_timestamp[sample.timestamp] = sample

    timestamps = sorted(by_timestamp)
    selected = [
        by_timestamp[timestamp]
        for timestamp in timestamps[-REQUIRED_SAMPLES:]
    ]

    if len(selected) < REQUIRED_SAMPLES:
        status = "inconclusive"
        reason = "Insufficient distinct post-action measurements."
    elif all(sample.value <= ERROR_RATE_THRESHOLD for sample in selected):
        status = "recovered"
        reason = "The latest three measurements meet the error-rate threshold."
    else:
        status = "not_recovered"
        reason = "At least one of the latest three measurements exceeds the threshold."

    return {
        "status": status,
        "reason": reason,
        "service": window.service,
        "threshold": ERROR_RATE_THRESHOLD,
        "required_samples": REQUIRED_SAMPLES,
        "evaluated_samples": [
            sample.model_dump(mode="json")
            for sample in selected
        ],
    }


def verify_simulated_remediation(remediation: dict) -> dict | None:
    if remediation.get("status") != "simulated":
        return None

    window = get_simulated_recovery_window(remediation)

    return {
        "mode": "simulation",
        **verify_recovery(window),
    }
