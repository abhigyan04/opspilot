from dataclasses import dataclass
from pathlib import Path

from ollama import Client

from app.retrieval import embeddings
from app.retrieval.chunks import KnowledgeChunk, chunk_document
from app.retrieval.documents import DEFAULT_KNOWLEDGE_DIR, load_documents
from app.retrieval.index import load_index, save_index
from app.retrieval.provenance import build_manifest, manifest_fingerprint


@dataclass(frozen=True)
class PreparedIndex:
    path: Path
    reused: bool
    manifest: dict
    chunks: list[KnowledgeChunk]
    vectors: list[list[float]]


def prepare_index(index_dir: Path, *, knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR, client: Client | None = None) -> PreparedIndex:
    if client is None:
        client = Client(host="http://localhost:11434")

    documents = load_documents(knowledge_dir)
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document)
    ]

    identity = embeddings.get_embedding_identity(client=client)
    manifest = build_manifest(chunks, identity)
    path = index_dir / f"{manifest_fingerprint(manifest)}.json"
    reused = path.exists()

    if reused:
        vectors = load_index(path, expected_manifest=manifest)
    else:
        vectors = embeddings.embed_chunks(chunks, client=client)

    current_identity = embeddings.get_embedding_identity(client=client)
    if current_identity != identity:
        raise ValueError("Embedding model identity changed during preparation.")

    if not reused:
        save_index(path, manifest, vectors)

    return PreparedIndex(
        path=path,
        reused=reused,
        manifest=manifest,
        chunks=chunks,
        vectors=vectors,
    )
