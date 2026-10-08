def build_citation_view(report: dict) -> list[dict]:
    diagnosis = report.get("diagnosis")
    if diagnosis is None or diagnosis["status"] != "supported":
        return []

    investigation = report.get("investigation") or {}
    observations = {}

    for step in investigation.get("steps", []):
        evidence_id = step["evidence_id"]
        if evidence_id in observations:
            raise ValueError(f"Duplicate evidence ID: {evidence_id}")

        observations[evidence_id] = {
            "evidence_id": evidence_id,
            "tool": step["decision"]["tool"],
            "arguments": step["decision"]["arguments"],
            "result": step["result"],
        }

    claims = [
        ("root_cause", diagnosis["root_cause"]),
        *[
            (f"supporting_claims[{index}]", claim)
            for index, claim in enumerate(diagnosis["supporting_claims"])
        ],
    ]

    return [
        {
            "claim_path": path,
            "statement": claim["statement"],
            "cited_observations": [
                observations[evidence_id]
                for evidence_id in claim["evidence_ids"]
                if evidence_id in observations
            ],
            "missing_evidence_ids": [
                evidence_id
                for evidence_id in claim["evidence_ids"]
                if evidence_id not in observations
            ],
        }
        for path, claim in claims
    ]
