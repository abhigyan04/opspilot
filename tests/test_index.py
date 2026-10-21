from copy import deepcopy
import json

import pytest

from app.retrieval.chunks import chunk_document
from app.retrieval.documents import load_documents
from app.retrieval.index import load_index, save_index
from app.retrieval.provenance import build_manifest


@pytest.fixture
def manifest():
    chunk = chunk_document(load_documents()[0])[0]
    return build_manifest(
        [chunk],
        {
            "model": "test-model",
            "digest": "a" * 64,
            "dimensions": 2,
            "format_version": 1,
        },
    )


def test_index_round_trip(tmp_path, manifest):
    path = tmp_path / "index.json"
    vectors = [[1.0, 0.5]]

    save_index(path, manifest, vectors)

    assert load_index(path, expected_manifest=manifest) == vectors


def test_existing_index_is_not_overwritten(tmp_path, manifest):
    path = tmp_path / "index.json"
    save_index(path, manifest, [[1.0, 0.0]])
    before = path.read_bytes()

    with pytest.raises(FileExistsError):
        save_index(path, manifest, [[0.0, 1.0]])

    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("digest", "b" * 64),
    ("format_version", 2),
    ("dimensions", 3),
])
def test_changed_model_identity_is_stale(tmp_path, manifest, field, value):
    path = tmp_path / "index.json"
    save_index(path, manifest, [[1.0, 0.0]])
    current = deepcopy(manifest)
    current["embedding"][field] = value

    with pytest.raises(ValueError, match="stale"):
        load_index(path, expected_manifest=current)


def test_changed_passage_is_stale(tmp_path, manifest):
    path = tmp_path / "index.json"
    save_index(path, manifest, [[1.0, 0.0]])
    current = deepcopy(manifest)
    current["chunks"][0]["content"] = "Updated guidance."

    with pytest.raises(ValueError, match="stale"):
        load_index(path, expected_manifest=current)


def test_accidental_vector_edit_is_detected(tmp_path, manifest):
    path = tmp_path / "index.json"
    save_index(path, manifest, [[1.0, 0.0]])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["vectors"][0][0] = 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="payload fingerprint"):
        load_index(path, expected_manifest=manifest)


@pytest.mark.parametrize("vectors", [
    [],
    [[1.0]],
    [[0.0, 0.0]],
    [[float("nan"), 1.0]],
    [[float("inf"), 1.0]],
    [[True, 1.0]],
    [["invalid", 1.0]],
])
def test_invalid_vectors_are_not_saved(tmp_path, manifest, vectors):
    path = tmp_path / "index.json"

    with pytest.raises(ValueError):
        save_index(path, manifest, vectors)

    assert not path.exists()


def test_malformed_file_is_rejected(tmp_path, manifest):
    path = tmp_path / "index.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="structure"):
        load_index(path, expected_manifest=manifest)
