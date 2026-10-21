from copy import deepcopy
import os
from uuid import uuid4

import psycopg
import pytest

from app.retrieval.chunks import chunk_document
from app.retrieval.documents import load_documents
from app.retrieval.index import save_index
from app.retrieval.pg_store import import_index, search_index
from app.retrieval.provenance import build_manifest, manifest_fingerprint


pytestmark = pytest.mark.integration


@pytest.fixture
def connection():
    dsn = os.environ.get("OPSPILOT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set OPSPILOT_TEST_DATABASE_URL to run database tests.")

    conn = psycopg.connect(dsn, connect_timeout=5)
    try:
        # Establish an outer transaction before the importer uses a savepoint.
        conn.execute("SELECT 1")
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def saved_index(tmp_path):
    chunks = chunk_document(load_documents()[0])[:2]
    manifest = build_manifest(chunks, {
        "model": "test-model",
        "digest": uuid4().hex + uuid4().hex,
        "dimensions": 768,
        "format_version": 1,
    })
    vectors = [
        [1.0, 0.0] + [0.0] * 766,
        [0.0, 1.0] + [0.0] * 766,
    ]
    path = tmp_path / "index.json"
    save_index(path, manifest, vectors)
    return path, manifest


def test_import_preserves_manifest_and_order(connection, saved_index):
    path, manifest = saved_index

    result = import_index(
        connection, path, expected_manifest=manifest
    )

    assert result["imported_passages"] == 2
    assert result["index_id"] == manifest_fingerprint(manifest)

    stored = connection.execute(
        """
        SELECT manifest, expected_passages
        FROM retrieval.indexes WHERE index_id = %s
        """,
        (result["index_id"],),
    ).fetchone()
    assert stored == (manifest, 2)

    passages = connection.execute(
        """
        SELECT chunk_id, content, vector_dims(embedding)
        FROM retrieval.passages
        WHERE index_id = %s ORDER BY position
        """,
        (result["index_id"],),
    ).fetchall()
    assert passages == [
        (chunk["chunk_id"], chunk["content"], 768)
        for chunk in manifest["chunks"]
    ]


def test_duplicate_import_is_rejected_without_changing_rows(connection, saved_index):
    path, manifest = saved_index
    result = import_index(connection, path, expected_manifest=manifest)

    with pytest.raises(psycopg.errors.UniqueViolation):
        import_index(connection, path, expected_manifest=manifest)

    count = connection.execute(
        "SELECT count(*) FROM retrieval.passages WHERE index_id = %s",
        (result["index_id"],),
    ).fetchone()[0]
    assert count == 2


def test_invalid_second_passage_rolls_back_whole_import(connection, saved_index, tmp_path):
    _, manifest = saved_index
    invalid = deepcopy(manifest)
    invalid["chunks"][1]["document_type"] = "unknown"
    path = tmp_path / "invalid-index.json"
    save_index(
        path,
        invalid,
        [[1.0] + [0.0] * 767 for _ in invalid["chunks"]],
    )
    index_id = manifest_fingerprint(invalid)

    with pytest.raises(psycopg.errors.CheckViolation):
        import_index(connection, path, expected_manifest=invalid)

    assert connection.execute(
        "SELECT count(*) FROM retrieval.indexes WHERE index_id = %s",
        (index_id,),
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT count(*) FROM retrieval.passages WHERE index_id = %s",
        (index_id,),
    ).fetchone()[0] == 0


def test_stale_manifest_is_rejected_before_insertion(connection, saved_index):
    path, manifest = saved_index
    changed = deepcopy(manifest)
    changed["embedding"]["digest"] = "b" * 64

    with pytest.raises(ValueError, match="stale"):
        import_index(connection, path, expected_manifest=changed)

    assert connection.execute(
        "SELECT count(*) FROM retrieval.indexes WHERE index_id = %s",
        (manifest_fingerprint(changed),),
    ).fetchone()[0] == 0


def test_search_ranks_vectors_and_returns_metadata(connection, saved_index):
    path, manifest = saved_index
    import_index(connection, path, expected_manifest=manifest)

    hits = search_index(
        connection,
        [0.0, 1.0] + [0.0] * 766,
        expected_manifest=manifest,
        top_k=2,
    )

    assert [hit.chunk.chunk_id for hit in hits] == [
        manifest["chunks"][1]["chunk_id"],
        manifest["chunks"][0]["chunk_id"],
    ]
    assert [hit.score for hit in hits] == pytest.approx([1.0, 0.0])
    assert hits[0].chunk.content == manifest["chunks"][1]["content"]


def test_search_rejects_missing_index(connection, saved_index):
    _, manifest = saved_index

    with pytest.raises(ValueError, match="not imported"):
        search_index(
            connection,
            [1.0] + [0.0] * 767,
            expected_manifest=manifest,
        )


def test_search_rejects_incomplete_index(connection, saved_index):
    path, manifest = saved_index
    result = import_index(connection, path, expected_manifest=manifest)
    connection.execute(
        """
        DELETE FROM retrieval.passages
        WHERE index_id = %s AND position = 1
        """,
        (result["index_id"],),
    )

    with pytest.raises(ValueError, match="passage count"):
        search_index(
            connection,
            [1.0] + [0.0] * 767,
            expected_manifest=manifest,
        )


def test_search_detects_changed_returned_content(connection, saved_index):
    path, manifest = saved_index
    result = import_index(connection, path, expected_manifest=manifest)
    connection.execute(
        """
        UPDATE retrieval.passages SET content = %s
        WHERE index_id = %s AND position = 0
        """,
        ("Unexpected replacement.", result["index_id"]),
    )

    with pytest.raises(ValueError, match="passage metadata"):
        search_index(
            connection,
            [1.0] + [0.0] * 767,
            expected_manifest=manifest,
            top_k=1,
        )


def test_search_ties_use_chunk_id_order(connection, saved_index):
    path, manifest = saved_index
    import_index(connection, path, expected_manifest=manifest)

    hits = search_index(
        connection,
        [1.0, 1.0] + [0.0] * 766,
        expected_manifest=manifest,
        top_k=2,
    )

    assert [hit.chunk.chunk_id for hit in hits] == sorted(
        chunk["chunk_id"] for chunk in manifest["chunks"]
    )


@pytest.mark.parametrize("vector", [
    [1.0, 0.0],
    [0.0] * 768,
    [float("nan")] + [0.0] * 767,
])
def test_search_rejects_invalid_query(connection, saved_index, vector):
    _, manifest = saved_index

    with pytest.raises(ValueError, match="Query"):
        search_index(connection, vector, expected_manifest=manifest)
