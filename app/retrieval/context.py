from dataclasses import asdict

from app.retrieval.search import SearchHit


def build_reference_context(hits: list[SearchHit]) -> list[dict]:
    references = []
    seen = set()

    for hit in hits:
        chunk = hit.chunk

        if chunk.chunk_id in seen:
            raise ValueError("Reference chunk IDs must be unique.")
        seen.add(chunk.chunk_id)

        if not chunk.content.strip():
            raise ValueError("Reference content must not be blank.")

        references.append({
            "reference_id": f"reference:{chunk.chunk_id}",
            **asdict(chunk),
        })

    return references
