import json
import math
from pathlib import Path

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.retrieval.index import load_index
from app.retrieval.provenance import manifest_fingerprint
from app.retrieval.chunks import KnowledgeChunk
from app.retrieval.search import SearchHit


def import_index(connection: Connection, source: Path, *, expected_manifest: dict) -> dict:
    vectors = load_index(source, expected_manifest=expected_manifest)
    chunks = expected_manifest["chunks"]

    if not chunks:
        raise ValueError("Cannot import an empty index.")

    if expected_manifest["embedding"]["dimensions"] != 768:
        raise ValueError("PostgreSQL storage requires 768 dimensions.")

    if len({chunk["chunk_id"] for chunk in chunks}) != len(chunks):
        raise ValueError("Chunk IDs must be unique.")

    index_id = manifest_fingerprint(expected_manifest)

    rows = [
        (
            index_id,
            chunk["chunk_id"],
            position,
            chunk["document_id"],
            chunk["document_type"],
            chunk["title"],
            chunk["section"],
            chunk["source_path"],
            chunk["synthetic"],
            chunk["source_sha256"],
            chunk["content"],
            json.dumps(vector, allow_nan=False),
        )
        for position, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]

    with connection.transaction():
        connection.execute(
            """
            INSERT INTO retrieval.indexes
                (index_id, manifest, expected_passages)
            VALUES (%s, %s, %s)
            """,
            (index_id, Jsonb(expected_manifest), len(chunks)),
        )

        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO retrieval.passages (
                    index_id, chunk_id, position, document_id,
                    document_type, title, section, source_path,
                    synthetic, source_sha256, content, embedding
                )
                VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s::vector
                )
                """,
                rows,
            )

    return {
        "index_id": index_id,
        "imported_passages": len(rows),
    }


def search_index(connection: Connection, query_vector: list[float], *, expected_manifest: dict, top_k: int = 3) -> list[SearchHit]:
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    if expected_manifest["embedding"]["dimensions"] != 768:
        raise ValueError("PostgreSQL storage requires 768 dimensions.")

    if len(query_vector) != 768:
        raise ValueError("Query must have 768 dimensions.")

    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in query_vector
    ):
        raise ValueError("Query values must be finite numbers.")

    if not any(value != 0 for value in query_vector):
        raise ValueError("Query must not be a zero vector.")

    index_id = manifest_fingerprint(expected_manifest)
    expected_chunks = {
        chunk["chunk_id"]: chunk
        for chunk in expected_manifest["chunks"]
    }
    if (
        not expected_chunks
        or len(expected_chunks) != len(expected_manifest["chunks"])
    ):
        raise ValueError("Manifest must contain nonempty, unique passages.")

    stored = connection.execute(
        """
        SELECT manifest, expected_passages
        FROM retrieval.indexes
        WHERE index_id = %s
        """,
        (index_id,),
    ).fetchone()

    if stored is None:
        raise ValueError("Requested index is not imported.")

    if (
        manifest_fingerprint(stored[0]) != index_id
        or stored[1] != len(expected_chunks)
    ):
        raise ValueError("Stored index metadata does not match the manifest.")

    count = connection.execute(
        "SELECT count(*) FROM retrieval.passages WHERE index_id = %s",
        (index_id,),
    ).fetchone()[0]

    if count != len(expected_chunks):
        raise ValueError("Stored passage count does not match the manifest.")

    rows = connection.execute(
        """
        SELECT
            to_jsonb(p) - 'embedding' - 'index_id' - 'position' AS chunk,
            1 - (embedding <=> %s::vector) AS score
        FROM retrieval.passages AS p
        WHERE index_id = %s
        ORDER BY score DESC, chunk_id COLLATE "C" ASC
        LIMIT %s
        """,
        (json.dumps(query_vector, allow_nan=False), index_id, top_k),
    ).fetchall()

    hits = []
    for chunk, score in rows:
        if chunk != expected_chunks.get(chunk["chunk_id"]):
            raise ValueError("Returned passage metadata differs from the manifest.")

        if score is None or not math.isfinite(score):
            raise ValueError("Database returned an invalid similarity score.")

        hits.append(SearchHit(
            chunk=KnowledgeChunk(**chunk),
            score=max(-1.0, min(1.0, score)),
        ))

    return hits
