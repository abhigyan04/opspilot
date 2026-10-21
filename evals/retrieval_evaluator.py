from app.retrieval.search import SearchHit
from evals.retrieval_cases import RetrievalCase


def evaluate_retrieval(case: RetrievalCase, hits: list[SearchHit], *, top_k: int = 3) -> dict:
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    selected = hits[:top_k]
    chunk_ids = [hit.chunk.chunk_id for hit in selected]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("Duplicate chunk IDs in selected results.")

    expected = case.relevant_sections
    matched = set()
    first_relevant_rank = None
    results = []

    for rank, hit in enumerate(selected, start=1):
        key = (hit.chunk.document_id, hit.chunk.section)
        relevant = key in expected

        if relevant:
            matched.add(key)
            if first_relevant_rank is None:
                first_relevant_rank = rank

        results.append({
            "rank": rank,
            "chunk_id": hit.chunk.chunk_id,
            "document_id": hit.chunk.document_id,
            "section": hit.chunk.section,
            "score": hit.score,
            "relevant": relevant,
        })

    answerable = bool(expected)

    return {
        "case_id": case.case_id,
        "query": case.query,
        "case_type": "positive" if answerable else "negative",
        "top_k": top_k,
        "returned_count": len(selected),
        "expected_sections": [
            {"document_id": document_id, "section": section}
            for document_id, section in sorted(expected)
        ],
        "matched_sections": len(matched),
        "hit_at_k": bool(matched) if answerable else None,
        "recall_at_k": len(matched) / len(expected) if answerable else None,
        "reciprocal_rank_at_k": (
            1 / first_relevant_rank if first_relevant_rank else 0.0
        ) if answerable else None,
        "returned_for_negative": (
            bool(selected) if not answerable else None
        ),
        "top_score": selected[0].score if selected else None,
        "results": results,
    }
