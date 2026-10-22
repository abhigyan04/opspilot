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


def note():
    return {
        "statement": "The runbook recommends comparing failures with deployments.",
        "reference_ids": ["reference:dependency-guide:abc:1"],
    }


def test_older_diagnosis_defaults_to_empty_reference_notes():
    result = diagnosis_adapter.validate_python(supported_payload())

    assert result.reference_notes == []


def test_reference_notes_are_separate_from_operational_claims():
    payload = supported_payload()
    payload["reference_notes"] = [note()]

    result = diagnosis_adapter.validate_python(payload)

    assert result.root_cause.evidence_ids == ["evidence-001"]
    assert result.reference_notes[0].reference_ids == [
        "reference:dependency-guide:abc:1"
    ]


def test_insufficient_evidence_can_include_background_guidance():
    payload = {
        "status": "insufficient_evidence",
        "reason": "Only symptoms were observed.",
        "missing_evidence": ["Failure details"],
        "reference_notes": [note()],
    }

    result = diagnosis_adapter.validate_python(payload)

    assert result.status == "insufficient_evidence"
    assert len(result.reference_notes) == 1


def test_reference_citations_cannot_replace_root_cause_evidence():
    payload = supported_payload()
    payload["root_cause"] = {
        "statement": "Payment authorization failed.",
        "reference_ids": ["reference:dependency-guide:abc:1"],
    }

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


@pytest.mark.parametrize("reference_note", [
    {
        "statement": "Background guidance",
        "reference_ids": [],
    },
    {
        "statement": "Background guidance",
        "reference_ids": ["a", "b", "c", "d"],
    },
    {
        "statement": "x" * 601,
        "reference_ids": ["reference:dependency-guide:abc:1"],
    },
    {
        "statement": "Background guidance",
        "evidence_ids": ["evidence-001"],
    },
])
def test_reference_note_structure_is_bounded(reference_note):
    payload = supported_payload()
    payload["reference_notes"] = [reference_note]

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)


def test_reference_note_count_is_bounded():
    payload = supported_payload()
    payload["reference_notes"] = [note() for _ in range(4)]

    with pytest.raises(ValidationError):
        diagnosis_adapter.validate_python(payload)
