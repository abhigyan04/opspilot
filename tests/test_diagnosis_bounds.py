from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agent.schemas import diagnosis_adapter


def supported_payload():
    return {
        "status": "supported",
        "root_cause": {
            "statement": "Payment authorization failed after a provider 503.",
            "evidence_ids": ["evidence-001"],
        },
        "supporting_claims": [],
        "limitations": [],
    }


def claim(statement):
    return {
        "statement": statement,
        "evidence_ids": ["evidence-001"],
    }


def test_supported_diagnosis_accepts_boundary_lengths():
    payload = supported_payload()
    payload["root_cause"]["statement"] = "x" * 600
    payload["supporting_claims"] = [
        claim(f"Observation {number}") for number in range(6)
    ]
    payload["limitations"] = ["y" * 600] * 4

    result = diagnosis_adapter.validate_python(payload)

    assert len(result.supporting_claims) == 6
    assert len(result.limitations) == 4


@pytest.mark.parametrize("field, value", [
    ("supporting_claims", [claim(f"Observation {n}") for n in range(7)]),
    ("limitations", ["Unknown cause"] * 5),
    ("limitations", ["x" * 601]),
])
def test_supported_diagnosis_rejects_excessive_output(field, value):
    payload = supported_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


@pytest.mark.parametrize("location", ["root_cause", "supporting_claims"])
def test_claim_statement_length_is_bounded(location):
    payload = supported_payload()
    oversized = claim("x" * 601)

    if location == "root_cause":
        payload["root_cause"] = oversized
    else:
        payload["supporting_claims"] = [oversized]

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


@pytest.mark.parametrize("repeat_root", [False, True])
def test_duplicate_claims_are_rejected_despite_case_and_whitespace(repeat_root):
    payload = supported_payload()

    if repeat_root:
        statement = payload["root_cause"]["statement"]
        payload["supporting_claims"] = [
            claim("  " + statement.upper() + "\n")
        ]
    else:
        payload["supporting_claims"] = [
            claim("Failures affect both versions."),
            claim("  FAILURES   AFFECT BOTH VERSIONS.\n"),
        ]

    with pytest.raises(ValidationError, match="duplicate claims"):
        diagnosis_adapter.validate_python(payload)


def test_claim_citation_count_is_bounded():
    payload = supported_payload()
    payload["root_cause"]["evidence_ids"] = [
        f"evidence-{number}" for number in range(13)
    ]

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


@pytest.mark.parametrize("field, value", [
    ("reason", "x" * 601),
    ("missing_evidence", ["Details"] * 7),
    ("missing_evidence", ["x" * 601]),
])
def test_insufficient_diagnosis_is_also_bounded(field, value):
    payload = {
        "status": "insufficient_evidence",
        "reason": "Only symptoms were observed.",
        "missing_evidence": ["Application logs"],
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


def test_repetition_loop_payload_is_rejected_without_modifying_it():
    payload = supported_payload()
    payload["supporting_claims"] = [
        claim("The failure is unrelated to other changes.")
        for _ in range(1534)
    ]
    original = deepcopy(payload)

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)

    assert payload == original


def test_generation_schema_contains_collection_and_text_limits():
    definitions = diagnosis_adapter.json_schema()["$defs"]
    supported = definitions["SupportedDiagnosis"]["properties"]
    evidence_claim = definitions["EvidenceClaim"]["properties"]

    assert supported["supporting_claims"]["maxItems"] == 6
    assert supported["limitations"]["maxItems"] == 4
    assert evidence_claim["statement"]["maxLength"] == 600
