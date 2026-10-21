import pytest
from dataclasses import replace
from types import SimpleNamespace


from app.retrieval.chunks import chunk_document
from app.retrieval.documents import load_documents

from app.retrieval.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    embed_texts,
    embed_chunks,
    embed_query,
    EMBEDDING_FORMAT_VERSION,
    get_embedding_identity
)


def make_vector(first=1.0):
    return [first] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


class FakeClient:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(embeddings=self.vectors)


def test_forwards_batch_without_truncation_and_preserves_order():
    vectors = [make_vector(1.0), make_vector(2.0)]
    client = FakeClient(vectors)
    texts = ["Dependency timeout.", "Application exception."]

    result = embed_texts(texts, client=client)

    assert result == vectors
    assert client.calls == [{
        "model": EMBEDDING_MODEL,
        "input": texts,
        "truncate": False,
    }]
    assert result[0] is not vectors[0]


def test_empty_batch_does_not_call_server():
    client = FakeClient([])

    assert embed_texts([], client=client) == []
    assert client.calls == []


@pytest.mark.parametrize("texts", [
    "not a list",
    [""],
    ["   "],
    [None],
    ["Valid text", 123],
])
def test_rejects_invalid_inputs_before_calling_server(texts):
    client = FakeClient([])

    with pytest.raises(ValueError):
        embed_texts(texts, client=client)

    assert client.calls == []


def test_rejects_wrong_number_of_vectors():
    client = FakeClient([make_vector()])

    with pytest.raises(ValueError, match="count"):
        embed_texts(["First", "Second"], client=client)


@pytest.mark.parametrize("vector", [
    [],
    [1.0, 2.0],
    [0.0] * EMBEDDING_DIMENSIONS,
    make_vector(float("nan")),
    make_vector(float("inf")),
    make_vector(True),
    make_vector("invalid"),
])
def test_rejects_invalid_vectors(vector):
    client = FakeClient([vector])

    with pytest.raises(ValueError):
        embed_texts(["Example"], client=client)


def test_server_errors_propagate():
    class FailingClient:
        def embed(self, **kwargs):
            raise ConnectionError("Ollama unavailable")

    with pytest.raises(ConnectionError, match="Ollama unavailable"):
        embed_texts(["Example"], client=FailingClient())


def test_query_uses_retrieval_prefix():
    client = FakeClient([make_vector()])

    result = embed_query("  Dependency timeout  ", client=client)

    assert result == make_vector()
    assert client.calls[0]["input"] == [
        "task: search result | query: Dependency timeout"
    ]


@pytest.mark.parametrize("query", ["", "   ", None, 123])
def test_invalid_query_does_not_call_server(query):
    client = FakeClient([])

    with pytest.raises(ValueError, match="Query"):
        embed_query(query, client=client)

    assert client.calls == []


def test_chunks_include_titles_sections_and_preserve_order():
    document = load_documents()[0]
    chunks = chunk_document(document)[:2]
    client = FakeClient([make_vector(1.0), make_vector(2.0)])

    result = embed_chunks(chunks, client=client)

    assert result == [make_vector(1.0), make_vector(2.0)]
    assert client.calls[0]["input"] == [
        f"title: {chunk.title} — {chunk.section} | text: {chunk.content}"
        for chunk in chunks
    ]
    assert client.calls[0]["truncate"] is False


def test_empty_chunks_do_not_call_server():
    client = FakeClient([])

    assert embed_chunks([], client=client) == []
    assert client.calls == []


def test_blank_chunk_is_rejected_before_prefix_can_hide_it():
    chunk = chunk_document(load_documents()[0])[0]
    blank = replace(chunk, content="   ")
    client = FakeClient([])

    with pytest.raises(ValueError, match="Chunk content"):
        embed_chunks([blank], client=client)

    assert client.calls == []


class FakeModelClient:
    def __init__(self, models):
        self.models = models

    def list(self):
        return SimpleNamespace(models=self.models)


def installed_model(name=EMBEDDING_MODEL, digest="a" * 64):
    return SimpleNamespace(model=name, digest=digest)


def test_reads_exact_embedding_model_identity():
    client = FakeModelClient([
        installed_model(name="another-model:latest"),
        installed_model(digest="B" * 64),
    ])

    assert get_embedding_identity(client=client) == {
        "model": EMBEDDING_MODEL,
        "digest": "b" * 64,
        "dimensions": EMBEDDING_DIMENSIONS,
        "format_version": EMBEDDING_FORMAT_VERSION,
    }


def test_missing_model_is_not_replaced_by_an_alias():
    client = FakeModelClient([
        installed_model(name="embeddinggemma:latest"),
    ])

    with pytest.raises(ValueError, match="exactly one"):
        get_embedding_identity(client=client)


def test_duplicate_model_entries_are_rejected():
    client = FakeModelClient([
        installed_model(),
        installed_model(),
    ])

    with pytest.raises(ValueError, match="exactly one"):
        get_embedding_identity(client=client)


@pytest.mark.parametrize("digest", [
    None,
    "",
    "abc",
    "g" * 64,
])
def test_invalid_model_digest_is_rejected(digest):
    client = FakeModelClient([
        installed_model(digest=digest),
    ])

    with pytest.raises(ValueError, match="digest"):
        get_embedding_identity(client=client)


def test_identity_lookup_connection_errors_propagate():
    class UnavailableClient:
        def list(self):
            raise ConnectionError("Ollama unavailable")

    with pytest.raises(ConnectionError, match="Ollama unavailable"):
        get_embedding_identity(client=UnavailableClient())
