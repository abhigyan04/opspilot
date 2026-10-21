import pytest

from app.retrieval.chunks import KnowledgeChunk
from app.retrieval.search import SearchHit
from evals.retrieval_cases import RetrievalCase
from evals.retrieval_evaluator import evaluate_retrieval


def make_hit(section, score=0.5, chunk_id=None):
    return SearchHit(
        chunk=KnowledgeChunk(
            chunk_id=chunk_id or section,
            document_id="example",
            document_type="runbook",
            title="Example",
            section=section,
            source_path="example.md",
            synthetic=True,
            source_sha256="a" * 64,
            content=f"Reference text for {section}.",
        ),
        score=score,
    )


def make_case(*sections):
    return RetrievalCase(
        case_id="example-query",
        query="What should I investigate?",
        relevant_sections=frozenset(
            ("example", section) for section in sections
        ),
    )


def test_partial_recall_and_second_place_match():
    result = evaluate_retrieval(
        make_case("Investigation", "Verification"),
        [
            make_hit("Symptoms", 0.8),
            make_hit("Investigation", 0.7),
            make_hit("Introduction", 0.6),
        ],
    )

    assert result["hit_at_k"] is True
    assert result["recall_at_k"] == 0.5
    assert result["reciprocal_rank_at_k"] == 0.5
    assert result["matched_sections"] == 1


def test_results_outside_top_k_do_not_count():
    result = evaluate_retrieval(
        make_case("Investigation"),
        [make_hit("Symptoms"), make_hit("Investigation")],
        top_k=1,
    )

    assert result["returned_count"] == 1
    assert result["hit_at_k"] is False
    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank_at_k"] == 0.0


def test_all_expected_sections_retrieved():
    result = evaluate_retrieval(
        make_case("Investigation", "Verification"),
        [make_hit("Investigation"), make_hit("Verification")],
    )

    assert result["recall_at_k"] == 1.0
    assert result["reciprocal_rank_at_k"] == 1.0


def test_repeated_section_does_not_inflate_recall():
    result = evaluate_retrieval(
        make_case("Investigation", "Verification"),
        [
            make_hit("Investigation", chunk_id="part-1"),
            make_hit("Investigation", chunk_id="part-2"),
        ],
    )

    assert result["matched_sections"] == 1
    assert result["recall_at_k"] == 0.5


def test_duplicate_chunk_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_retrieval(
            make_case("Investigation"),
            [make_hit("Investigation"), make_hit("Investigation")],
        )


@pytest.mark.parametrize("has_hits", [False, True])
def test_negative_cases_have_separate_diagnostics(has_hits):
    hits = [make_hit("Symptoms", 0.12)] if has_hits else []

    result = evaluate_retrieval(make_case(), hits)

    assert result["case_type"] == "negative"
    assert result["hit_at_k"] is None
    assert result["recall_at_k"] is None
    assert result["reciprocal_rank_at_k"] is None
    assert result["returned_for_negative"] is has_hits
    assert result["top_score"] == (0.12 if has_hits else None)


def test_empty_positive_results_score_zero():
    result = evaluate_retrieval(make_case("Investigation"), [])

    assert result["hit_at_k"] is False
    assert result["recall_at_k"] == 0.0
    assert result["reciprocal_rank_at_k"] == 0.0
    assert result["top_score"] is None


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_invalid_top_k_is_rejected(top_k):
    with pytest.raises(ValueError, match="top_k"):
        evaluate_retrieval(make_case(), [], top_k=top_k)
