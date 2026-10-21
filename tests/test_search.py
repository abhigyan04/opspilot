import pytest

from app.retrieval.chunks import KnowledgeChunk
from app.retrieval.search import rank_chunks


def make_chunk(chunk_id):
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="runbook-example",
        document_type="runbook",
        title="Example",
        section="Investigation",
        source_path="runbooks/example.md",
        synthetic=True,
        source_sha256="a" * 64,
        content=f"Reference passage {chunk_id}.",
    )


def test_ranks_by_direction_not_vector_magnitude():
    chunks = [make_chunk(name) for name in ["opposite", "side", "aligned"]]

    hits = rank_chunks(
        [2.0, 0.0],
        chunks,
        [[-5.0, 0.0], [0.0, 100.0], [3.0, 0.0]],
    )

    assert [hit.chunk.chunk_id for hit in hits] == [
        "aligned", "side", "opposite",
    ]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.0, -1.0])
    assert hits[0].chunk is chunks[2]


def test_top_k_limits_results():
    chunks = [make_chunk("a"), make_chunk("b")]

    hits = rank_chunks(
        [1.0, 0.0],
        chunks,
        [[1.0, 0.0], [0.0, 1.0]],
        top_k=1,
    )

    assert len(hits) == 1
    assert hits[0].chunk.chunk_id == "a"


def test_equal_scores_use_chunk_id_regardless_of_input_order():
    chunks = [make_chunk("b"), make_chunk("a")]
    vectors = [[1.0, 0.0], [1.0, 0.0]]

    first = rank_chunks([1.0, 0.0], chunks, vectors)
    second = rank_chunks(
        [1.0, 0.0], list(reversed(chunks)), list(reversed(vectors))
    )

    assert first == second
    assert [hit.chunk.chunk_id for hit in first] == ["a", "b"]


def test_empty_collection_returns_no_hits():
    assert rank_chunks([1.0, 0.0], [], []) == []


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_rejects_invalid_top_k(top_k):
    with pytest.raises(ValueError, match="top_k"):
        rank_chunks([1.0], [], [], top_k=top_k)


def test_rejects_mismatched_counts():
    with pytest.raises(ValueError, match="counts"):
        rank_chunks([1.0], [make_chunk("a")], [])


def test_rejects_duplicate_chunk_ids():
    with pytest.raises(ValueError, match="unique"):
        rank_chunks(
            [1.0],
            [make_chunk("a"), make_chunk("a")],
            [[1.0], [1.0]],
        )


def test_rejects_mismatched_dimensions():
    with pytest.raises(ValueError, match="dimensions"):
        rank_chunks([1.0, 0.0], [make_chunk("a")], [[1.0]])


@pytest.mark.parametrize("vector", [
    [],
    [0.0, 0.0],
    [float("nan"), 1.0],
    [float("inf"), 1.0],
    [True, 1.0],
])
def test_rejects_invalid_query_vectors(vector):
    with pytest.raises(ValueError):
        rank_chunks(vector, [], [])


def test_rejects_invalid_passage_vector():
    with pytest.raises(ValueError):
        rank_chunks(
            [1.0, 0.0],
            [make_chunk("a")],
            [[0.0, 0.0]],
        )


def test_handles_large_finite_values():
    hits = rank_chunks(
        [1e308, 1e308],
        [make_chunk("a")],
        [[1e308, 1e308]],
    )

    assert hits[0].score == pytest.approx(1.0)
