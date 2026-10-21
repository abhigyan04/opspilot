from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json

from app.retrieval import chunks as chunking
from app.retrieval.chunks import KnowledgeChunk


def build_manifest(chunks: list[KnowledgeChunk], embedding_identity: dict) -> dict:
    if not chunks:
        raise ValueError("Cannot build an index manifest without passages.")

    ids = [chunk.chunk_id for chunk in chunks]
    if len(set(ids)) != len(ids):
        raise ValueError("Chunk IDs must be unique.")

    return {
        "manifest_version": 1,
        "chunking_version": chunking.CHUNKING_VERSION,
        "embedding": deepcopy(embedding_identity),
        # Preserve order: vectors must correspond to these exact passages.
        "chunks": [asdict(chunk) for chunk in chunks],
    }


def manifest_fingerprint(manifest: dict) -> str:
    canonical = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
