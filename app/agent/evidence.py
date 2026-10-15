from copy import deepcopy
from datetime import datetime


def build_evidence_timeline(steps: list[dict]) -> list[dict]:
    events = []

    for step in steps:
        result = step["result"]
        records = result if isinstance(result, list) else [result]

        for record in records:
            if not isinstance(record, dict):
                continue

            timestamp = record.get("timestamp")
            if not isinstance(timestamp, str):
                continue

            try:
                instant = datetime.fromisoformat(timestamp)
            except ValueError:
                continue

            if instant.utcoffset() is None:
                continue

            events.append((
                instant,
                {
                    "evidence_id": step["evidence_id"],
                    "tool": step["decision"]["tool"],
                    "record": deepcopy(record),
                },
            ))

    events.sort(key=lambda event: event[0])
    return [event for _, event in events]
