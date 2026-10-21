import pytest

from app.retrieval import pg_retrieve
from app.retrieval.provenance import manifest_fingerprint


@pytest.fixture
def backend(monkeypatch):
    state = {
        "identity_calls": 0,
        "queries": [],
        "search_calls": [],
        "change_identity": False,
        "hits": [],
    }

    def identity(*, client=None):
        state["identity_calls"] += 1
        changed = (
            state["change_identity"]
            and state["identity_calls"] > 1
        )
        return {
            "model": "embeddinggemma:300m",
            "digest": ("b" if changed else "a") * 64,
            "dimensions": 768,
            "format_version": 1,
        }

    def embed_query(query, *, client=None):
        state["queries"].append((query, client))
        return [1.0] + [0.0] * 767

    def search(connection, vector, *, expected_manifest, top_k):
        state["search_calls"].append({
            "connection": connection,
            "vector": vector,
            "manifest": expected_manifest,
            "top_k": top_k,
        })
        return state["hits"]

    def unexpected_passage_embedding(*args, **kwargs):
        pytest.fail("Search must not embed passages.")

    monkeypatch.setattr(
        pg_retrieve.embeddings, "get_embedding_identity", identity
    )
    monkeypatch.setattr(
        pg_retrieve.embeddings, "embed_query", embed_query
    )
    monkeypatch.setattr(
        pg_retrieve.embeddings, "embed_chunks",
        unexpected_passage_embedding,
    )
    monkeypatch.setattr(pg_retrieve.pg_store, "search_index", search)
    return state


def test_forwards_current_manifest_query_and_connection(backend):
    connection = object()
    client = object()

    result = pg_retrieve.retrieve_postgres(
        "Dependency errors",
        connection,
        top_k=2,
        client=client,
    )

    assert backend["identity_calls"] == 2
    assert backend["queries"] == [("Dependency errors", client)]
    assert len(backend["search_calls"]) == 1

    call = backend["search_calls"][0]
    assert call["connection"] is connection
    assert call["top_k"] == 2
    assert len(call["manifest"]["chunks"]) == 14
    assert call["vector"] == [1.0] + [0.0] * 767
    assert result.index_id == manifest_fingerprint(call["manifest"])
    assert result.embedding_identity == call["manifest"]["embedding"]
    assert result.hits is backend["hits"]


def test_identity_change_prevents_database_search(backend):
    backend["change_identity"] = True

    with pytest.raises(ValueError, match="identity changed"):
        pg_retrieve.retrieve_postgres("Dependency errors", object())

    assert backend["search_calls"] == []


@pytest.mark.parametrize("query,top_k", [
    ("", 3),
    ("   ", 3),
    ("Valid query", 0),
    ("Valid query", True),
])
def test_invalid_request_fails_before_backend_calls(backend, query, top_k):
    with pytest.raises(ValueError):
        pg_retrieve.retrieve_postgres(query, object(), top_k=top_k)

    assert backend["identity_calls"] == 0
    assert backend["queries"] == []
    assert backend["search_calls"] == []


def test_missing_import_error_propagates(backend, monkeypatch):
    def missing(*args, **kwargs):
        raise ValueError("Requested index is not imported.")

    monkeypatch.setattr(pg_retrieve.pg_store, "search_index", missing)

    with pytest.raises(ValueError, match="not imported"):
        pg_retrieve.retrieve_postgres("Dependency errors", object())


def test_query_embedding_failure_prevents_search(backend, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("Ollama unavailable")

    monkeypatch.setattr(
        pg_retrieve.embeddings, "embed_query", unavailable
    )

    with pytest.raises(ConnectionError):
        pg_retrieve.retrieve_postgres("Dependency errors", object())

    assert backend["search_calls"] == []
