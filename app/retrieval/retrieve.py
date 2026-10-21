from dataclasses import dataclass
from pathlib import Path

from ollama import Client

from app.retrieval import embeddings
from app.retrieval.documents import DEFAULT_KNOWLEDGE_DIR
from app.retrieval.prepare import prepare_index
from app.retrieval.search import SearchHit, rank_chunks


@dataclass(frozen=True)
class RetrievalResult:
    index_path: Path
    index_reused: bool
    embedding_identity: dict
    hits: list[SearchHit]


def retrieve(query: str, index_dir: Path, *, top_k: int = 3, knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR, client: Client | None = None) -> RetrievalResult:
    # Reject invalid requests before preparing an index or contacting Ollama.
    embeddings.format_query(query)
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    if client is None:
        client = Client(host="http://localhost:11434")

    index = prepare_index(
        index_dir,
        knowledge_dir=knowledge_dir,
        client=client,
    )
    expected_identity = index.manifest["embedding"]

    query_vector = embeddings.embed_query(query, client=client)

    current_identity = embeddings.get_embedding_identity(client=client)
    if current_identity != expected_identity:
        raise ValueError("Embedding model identity changed during query embedding.")

    hits = rank_chunks(
        query_vector,
        index.chunks,
        index.vectors,
        top_k=top_k,
    )

    return RetrievalResult(
        index_path=index.path,
        index_reused=index.reused,
        embedding_identity=dict(expected_identity),
        hits=hits,
    )
