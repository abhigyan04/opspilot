from dataclasses import dataclass
import math

from app.retrieval.chunks import KnowledgeChunk


@dataclass(frozen=True)
class SearchHit:
    chunk: KnowledgeChunk
    score: float


def _normalize(vector: list[float]) -> list[float]:
    if not vector:
        raise ValueError("Vector must not be empty.")

    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in vector
    ):
        raise ValueError("Vector values must be finite numbers.")

    # Scaling first avoids overflow when computing the norm.
    scale = max(abs(value) for value in vector)
    if scale == 0:
        raise ValueError("Vector must not be zero.")

    scaled = [value / scale for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    return [value / norm for value in scaled]


def rank_chunks(query_vector: list[float], chunks: list[KnowledgeChunk], vectors: list[list[float]], *, top_k: int = 3) -> list[SearchHit]:
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    if len(chunks) != len(vectors):
        raise ValueError("Chunk and vector counts must match.")

    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Chunk IDs must be unique.")

    query = _normalize(query_vector)
    hits = []

    for chunk, vector in zip(chunks, vectors):
        if len(vector) != len(query):
            raise ValueError("Query and passage dimensions must match.")

        passage = _normalize(vector)
        score = math.fsum(
            left * right
            for left, right in zip(query, passage)
        )
        # Floating-point rounding can otherwise slightly exceed these bounds.
        score = max(-1.0, min(1.0, score))
        hits.append(SearchHit(chunk=chunk, score=score))

    hits.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
    return hits[:top_k]
