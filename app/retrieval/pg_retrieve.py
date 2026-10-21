from dataclasses import dataclass
from pathlib import Path

from ollama import Client
from psycopg import Connection

from app.retrieval import embeddings, pg_store
from app.retrieval.chunks import chunk_document
from app.retrieval.documents import DEFAULT_KNOWLEDGE_DIR, load_documents
from app.retrieval.provenance import build_manifest, manifest_fingerprint
from app.retrieval.search import SearchHit


@dataclass(frozen=True)
class PostgresRetrievalResult:
    index_id: str
    embedding_identity: dict
    hits: list[SearchHit]


def retrieve_postgres(query: str, connection: Connection, *, top_k: int = 3, knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR, client: Client | None = None) -> PostgresRetrievalResult:
    embeddings.format_query(query)
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    if client is None:
        client = Client(host="http://localhost:11434")

    chunks = [
        chunk
        for document in load_documents(knowledge_dir)
        for chunk in chunk_document(document)
    ]

    identity = embeddings.get_embedding_identity(client=client)
    manifest = build_manifest(chunks, identity)
    query_vector = embeddings.embed_query(query, client=client)

    if embeddings.get_embedding_identity(client=client) != identity:
        raise ValueError("Embedding model identity changed during query embedding.")

    hits = pg_store.search_index(
        connection,
        query_vector,
        expected_manifest=manifest,
        top_k=top_k,
    )

    return PostgresRetrievalResult(
        index_id=manifest_fingerprint(manifest),
        embedding_identity=dict(identity),
        hits=hits,
    )
