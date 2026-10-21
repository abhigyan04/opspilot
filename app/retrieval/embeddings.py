import math

from ollama import Client

from app.retrieval.chunks import KnowledgeChunk


EMBEDDING_MODEL = "embeddinggemma:300m"
EMBEDDING_DIMENSIONS = 768


def embed_texts(texts: list[str], *, client: Client | None = None) -> list[list[float]]:
    if not isinstance(texts, list):
        raise ValueError("texts must be a list of strings.")

    if any(
        not isinstance(text, str) or not text.strip()
        for text in texts
    ):
        raise ValueError("Embedding inputs must be nonblank strings.")

    if not texts:
        return []

    if client is None:
        client = Client(host="http://localhost:11434")

    response = client.embed(
        model=EMBEDDING_MODEL,
        input=texts,
        truncate=False,
    )
    vectors = response.embeddings

    if len(vectors) != len(texts):
        raise ValueError("Embedding count does not match input count.")

    validated = []
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError("Unexpected embedding dimensions.")

        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ):
            raise ValueError("Embedding values must be finite numbers.")

        if not any(value != 0 for value in vector):
            raise ValueError("Embedding must not be a zero vector.")

        validated.append([float(value) for value in vector])

    return validated


# Increment when retrieval input formatting changes.
EMBEDDING_FORMAT_VERSION = 1


def format_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must be a nonblank string.")

    return f"task: search result | query: {query.strip()}"


def format_chunk(chunk: KnowledgeChunk) -> str:
    if not chunk.content.strip():
        raise ValueError("Chunk content must not be blank.")

    title = f"{chunk.title} — {chunk.section}"
    return f"title: {title} | text: {chunk.content}"


def embed_query(query: str, *, client: Client | None = None) -> list[float]:
    return embed_texts(
        [format_query(query)],
        client=client,
    )[0]


def embed_chunks(chunks: list[KnowledgeChunk], *, client: Client | None = None) -> list[list[float]]:
    return embed_texts(
        [format_chunk(chunk) for chunk in chunks],
        client=client,
    )
