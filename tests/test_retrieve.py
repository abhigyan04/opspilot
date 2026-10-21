import pytest

from app.retrieval.retrieve import retrieve
from app.retrieval import embeddings


@pytest.fixture
def backend(monkeypatch):
    state = {
        "digest": "a" * 64,
        "passage_calls": 0,
        "query_calls": 0,
        "identity_calls": 0,
        "change_during_query": False,
    }

    def identity(*, client=None):
        state["identity_calls"] += 1
        return {
            "model": "test-model",
            "digest": state["digest"],
            "dimensions": 2,
            "format_version": 1,
        }

    def passages(chunks, *, client=None):
        state["passage_calls"] += 1
        return [[1.0, 0.0] for _ in chunks]

    def query(text, *, client=None):
        state["query_calls"] += 1
        if state["change_during_query"]:
            state["digest"] = "b" * 64
        return [1.0, 0.0]

    monkeypatch.setattr(embeddings, "get_embedding_identity", identity)
    monkeypatch.setattr(embeddings, "embed_chunks", passages)
    monkeypatch.setattr(embeddings, "embed_query", query)
    return state


def test_searches_reused_index_without_reembedding_passages(tmp_path, backend):
    first = retrieve("Dependency errors", tmp_path, top_k=2)
    second = retrieve("Application exceptions", tmp_path, top_k=2)

    assert first.index_reused is False
    assert second.index_reused is True
    assert first.index_path == second.index_path
    assert backend["passage_calls"] == 1
    assert backend["query_calls"] == 2
    assert backend["identity_calls"] == 6
    assert len(second.hits) == 2
    assert all(hit.chunk.content for hit in second.hits)


def test_model_change_during_query_is_rejected(tmp_path, backend):
    backend["change_during_query"] = True

    with pytest.raises(ValueError, match="during query embedding"):
        retrieve("Dependency errors", tmp_path)


def test_changed_model_before_search_builds_new_index(tmp_path, backend):
    first = retrieve("Dependency errors", tmp_path)

    backend["digest"] = "b" * 64
    second = retrieve("Dependency errors", tmp_path)

    assert second.index_reused is False
    assert second.index_path != first.index_path
    assert second.embedding_identity["digest"] == "b" * 64
    assert backend["passage_calls"] == 2


@pytest.mark.parametrize("query,top_k", [
    ("", 3),
    ("   ", 3),
    ("Valid query", 0),
    ("Valid query", True),
])
def test_invalid_requests_do_not_contact_backend(tmp_path, backend, query, top_k):
    with pytest.raises(ValueError):
        retrieve(query, tmp_path, top_k=top_k)

    assert backend["identity_calls"] == 0
    assert backend["passage_calls"] == 0
    assert backend["query_calls"] == 0
    assert list(tmp_path.iterdir()) == []


def test_query_failure_does_not_damage_saved_index(tmp_path, backend, monkeypatch):
    first = retrieve("Dependency errors", tmp_path)
    before = first.index_path.read_bytes()

    def fail(query, *, client=None):
        raise ConnectionError("Ollama unavailable")

    monkeypatch.setattr(embeddings, "embed_query", fail)

    with pytest.raises(ConnectionError):
        retrieve("Another query", tmp_path)

    assert first.index_path.read_bytes() == before
    assert backend["passage_calls"] == 1
