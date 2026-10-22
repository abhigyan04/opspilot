QUERY_VERSION = 2
MAX_INCIDENT_CHARS = 400
MAX_MESSAGE_CHARS = 300
MAX_MESSAGES = 3


def build_retrieval_query(incident: str, steps: list[dict]) -> str:
    if not isinstance(incident, str) or not incident.strip():
        raise ValueError("Incident must be a nonblank string.")

    incident_text = " ".join(incident.split())[:MAX_INCIDENT_CHARS]
    lines = []
    seen = set()

    for step in steps:
        decision = step.get("decision", {})
        if decision.get("tool") != "search_logs":
            continue

        records = step.get("result")
        if not isinstance(records, list):
            continue

        requested_level = decision.get("arguments", {}).get("level")

        for record in records:
            if not isinstance(record, dict):
                continue

            level = record.get("level", requested_level)
            if level not in {"ERROR", "CRITICAL"}:
                continue

            message = record.get("message")
            if not isinstance(message, str) or not message.strip():
                continue

            text = " ".join(message.split())[:MAX_MESSAGE_CHARS]
            if text in seen:
                continue

            seen.add(text)
            lines.append(text)

            if len(seen) == MAX_MESSAGES:
                return "\n".join(lines)

    return "\n".join(lines) if lines else incident_text
