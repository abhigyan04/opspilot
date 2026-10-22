import json
from types import SimpleNamespace

import pytest

from app.agent import agent
from app.retrieval.chunks import KnowledgeChunk
from app.retrieval.context import build_reference_context
from app.retrieval.search import SearchHit


def make_hit():
    return SearchHit(
        chunk=KnowledgeChunk(
            chunk_id="reference-document:abc:1",
            document_id="reference-document",
            document_type="runbook",
            title="Dependency investigation",
            section="Investigation",
            source_path="runbooks/dependency.md",
            synthetic=True,
            source_sha256="a" * 64,
            content="Compare failures with deployment timing.",
        ),
        score=0.8,
    )


def make_steps():
    return [{
        "evidence_id": "evidence-001",
        "decision": {
            "tool": "search_logs",
            "arguments": {"service": "checkout-service", "level": "ERROR"},
        },
        "result": [{"message": "Checkout failed after an upstream timeout."}],
    }]


@pytest.mark.parametrize("cite_reference", [False, True])
def test_references_are_separate_from_operational_citations(monkeypatch, cite_reference):
    hit = make_hit()
    reference_id = f"reference:{hit.chunk.chunk_id}"
    cited_id = reference_id if cite_reference else "evidence-001"

    def fake_chat(**kwargs):
        supplied = json.loads(kwargs["messages"][-1]["content"])
        assert supplied["references"] == build_reference_context([hit])
        assert supplied["observations"][0]["evidence_id"] == "evidence-001"

        allowed = kwargs["format"]["$defs"]["EvidenceClaim"][
            "properties"
        ]["evidence_ids"]["items"]["enum"]
        assert allowed == ["evidence-001"]

        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps({
                "status": "supported",
                "root_cause": {
                    "statement": "Checkout failed after an upstream timeout.",
                    "evidence_ids": [cited_id],
                },
                "supporting_claims": [],
                "limitations": ["The upstream timeout's cause is unknown."],
            }))
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    if cite_reference:
        with pytest.raises(ValueError, match="unknown evidence IDs"):
            agent.generate_diagnosis(
                "Investigate checkout failures.",
                make_steps(),
                reference_hits=[hit],
            )
    else:
        result = agent.generate_diagnosis(
            "Investigate checkout failures.",
            make_steps(),
            reference_hits=[hit],
        )
        assert result.status == "supported"


def test_references_cannot_replace_missing_operational_evidence(monkeypatch):
    def unexpected_chat(**kwargs):
        pytest.fail("References alone must not trigger diagnosis generation.")

    monkeypatch.setattr(agent, "chat", unexpected_chat)

    result = agent.generate_diagnosis(
        "Investigate checkout failures.",
        [],
        reference_hits=[make_hit()],
    )

    assert result.status == "insufficient_evidence"
    assert result.missing_evidence == ["Operational tool results"]


@pytest.mark.parametrize("status", ["supported", "insufficient_evidence"])
@pytest.mark.parametrize("citation_kind", [
    "valid",
    "unknown",
    "operational",
    "not_supplied",
    "empty_notes",
])
def test_generated_reference_notes_validate_against_supplied_passages(monkeypatch, status, citation_kind):
    hit = make_hit()
    reference_id = f"reference:{hit.chunk.chunk_id}"

    cited_id = {
        "valid": reference_id,
        "unknown": "reference:missing-document:abc:1",
        "operational": "evidence-001",
        "not_supplied": reference_id,
        "empty_notes": reference_id,
    }[citation_kind]

    notes = [] if citation_kind == "empty_notes" else [{
        "statement": "The runbook recommends comparing failure and deployment timing.",
        "reference_ids": [cited_id],
    }]

    if status == "supported":
        payload = {
            "status": "supported",
            "root_cause": {
                "statement": "Checkout failed after an upstream timeout.",
                "evidence_ids": ["evidence-001"],
            },
            "supporting_claims": [],
            "limitations": ["The dependency's internal cause is unknown."],
            "reference_notes": notes,
        }
    else:
        payload = {
            "status": "insufficient_evidence",
            "reason": "The observations do not establish the timeout's cause.",
            "missing_evidence": ["Dependency failure details"],
            "reference_notes": notes,
        }

    def fake_chat(**kwargs):
        return SimpleNamespace(
            done_reason="stop",
            message=SimpleNamespace(content=json.dumps(payload)),
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    supplied_hits = (
        []
        if citation_kind in {"not_supplied", "empty_notes"}
        else [hit]
    )

    if citation_kind in {"unknown", "operational", "not_supplied"}:
        with pytest.raises(ValueError, match="unknown reference IDs"):
            agent.generate_diagnosis(
                "Investigate checkout failures.",
                make_steps(),
                reference_hits=supplied_hits,
            )
    else:
        result = agent.generate_diagnosis(
            "Investigate checkout failures.",
            make_steps(),
            reference_hits=supplied_hits,
        )
        assert result.status == status
        assert [
            note.model_dump() for note in result.reference_notes
        ] == notes


@pytest.mark.parametrize("with_references", [False, True])
def test_generation_schema_restricts_reference_notes(monkeypatch, with_references):
    hit = make_hit()
    reference_id = f"reference:{hit.chunk.chunk_id}"

    def fake_chat(**kwargs):
        definitions = kwargs["format"]["$defs"]

        # Operational citations remain independent of reference citations.
        assert definitions["EvidenceClaim"]["properties"][
            "evidence_ids"
        ]["items"]["enum"] == ["evidence-001"]

        if with_references:
            assert definitions["ReferenceNote"]["properties"][
                "reference_ids"
            ]["items"]["enum"] == [reference_id]

        for definition in ("SupportedDiagnosis", "InsufficientEvidence"):
            assert definitions[definition]["properties"][
                "reference_notes"
            ]["maxItems"] == (3 if with_references else 0)

        return SimpleNamespace(
            done_reason="stop",
            message=SimpleNamespace(content=json.dumps({
                "status": "insufficient_evidence",
                "reason": "The timeout's underlying cause is unknown.",
                "missing_evidence": ["Dependency failure details"],
                "reference_notes": [],
            })),
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    result = agent.generate_diagnosis(
        "Investigate checkout failures.",
        make_steps(),
        reference_hits=[hit] if with_references else [],
    )

    assert result.reference_notes == []
