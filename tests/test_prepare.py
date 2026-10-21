import pytest

from app.retrieval import prepare


@pytest.fixture
def fake_embedding_backend(monkeypatch):
    state = {
        "digest": "a" * 64,
        "embedding_calls": 0,
        "identity_calls": 0,
    }

    def identity(*, client=None):
        state["identity_calls"] += 1
        return {
            "model": "test-model",
            "digest": state["digest"],
            "dimensions": 2,
            "format_version": 1,
        }

    def embed(chunks, *, client=None):
        state["embedding_calls"] += 1
        return [[1.0, 0.0] for _ in chunks]

    monkeypatch.setattr(
        prepare.embeddings, "get_embedding_identity", identity
    )
    monkeypatch.setattr(prepare.embeddings, "embed_chunks", embed)
    return state


def test_second_preparation_reuses_vectors(tmp_path, fake_embedding_backend):
    first = prepare.prepare_index(tmp_path)
    second = prepare.prepare_index(tmp_path)

    assert first.reused is False
    assert second.reused is True
    assert first.path == second.path
    assert first.vectors == second.vectors
    assert len(first.chunks) == len(first.vectors) == 14
    assert fake_embedding_backend["embedding_calls"] == 1
    assert fake_embedding_backend["identity_calls"] == 4


def test_changed_model_creates_separate_index(tmp_path, fake_embedding_backend):
    first = prepare.prepare_index(tmp_path)
    original_bytes = first.path.read_bytes()

    fake_embedding_backend["digest"] = "b" * 64
    second = prepare.prepare_index(tmp_path)

    assert second.reused is False
    assert first.path != second.path
    assert first.path.read_bytes() == original_bytes
    assert fake_embedding_backend["embedding_calls"] == 2


def test_model_change_during_embedding_prevents_save(tmp_path, fake_embedding_backend, monkeypatch):
    def changing_embed(chunks, *, client=None):
        fake_embedding_backend["digest"] = "b" * 64
        return [[1.0, 0.0] for _ in chunks]

    monkeypatch.setattr(
        prepare.embeddings, "embed_chunks", changing_embed
    )

    with pytest.raises(ValueError, match="identity changed"):
        prepare.prepare_index(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_corrupt_index_is_not_silently_rebuilt(tmp_path, fake_embedding_backend):
    first = prepare.prepare_index(tmp_path)
    first.path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="structure"):
        prepare.prepare_index(tmp_path)

    assert fake_embedding_backend["embedding_calls"] == 1
    assert first.path.read_text(encoding="utf-8") == "{}"
