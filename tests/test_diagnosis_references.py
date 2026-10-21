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
