import json
import os
from uuid import uuid4

import psycopg
import pytest


pytestmark = pytest.mark.integration


@pytest.fixture
def connection():
    dsn = os.environ.get("OPSPILOT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set OPSPILOT_TEST_DATABASE_URL to run database tests.")

    conn = psycopg.connect(dsn, connect_timeout=5)
    try:
        yield conn
    finally:
        # Never commit test records, including when an assertion fails.
        conn.rollback()
        conn.close()


@pytest.fixture
def index_id(connection):
    identifier = uuid4().hex + uuid4().hex
    connection.execute(
        """
        INSERT INTO retrieval.indexes
            (index_id, manifest, expected_passages)
        VALUES (%s, %s::jsonb, %s)
        """,
        (identifier, "{}", 1),
    )
    return identifier


def insert_passage(
    connection,
    index_id,
    *,
    chunk_id="test-chunk",
    position=0,
    content="Synthetic test passage.",
    document_type="runbook",
    vector=None,
):
    if vector is None:
        vector = [1.0] + [0.0] * 767

    connection.execute(
        """
        INSERT INTO retrieval.passages (
            index_id, chunk_id, position, document_id, document_type,
            title, section, source_path, synthetic, source_sha256,
            content, embedding
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s::vector
        )
        """,
        (
            index_id, chunk_id, position, "test-document", document_type,
            "Test", "Investigation", "test.md", True, "a" * 64,
            content, json.dumps(vector, allow_nan=False),
        ),
    )


def test_valid_passage_has_expected_dimensions(connection, index_id):
    insert_passage(connection, index_id)

    row = connection.execute(
        """
        SELECT vector_dims(embedding), content
        FROM retrieval.passages
        WHERE index_id = %s
        """,
        (index_id,),
    ).fetchone()

    assert row == (768, "Synthetic test passage.")


def test_passage_requires_existing_index(connection):
    missing_id = uuid4().hex + uuid4().hex

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_passage(connection, missing_id)


def test_duplicate_chunk_within_index_is_rejected(connection, index_id):
    insert_passage(connection, index_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_passage(connection, index_id, position=1)


def test_duplicate_position_within_index_is_rejected(connection, index_id):
    insert_passage(connection, index_id)

    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_passage(connection, index_id, chunk_id="another-chunk")


@pytest.mark.parametrize("overrides", [
    {"position": -1},
    {"content": ""},
    {"document_type": "unknown"},
    {"vector": [0.0] * 768},
])
def test_invalid_passage_values_are_rejected(connection, index_id, overrides):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_passage(connection, index_id, **overrides)


def test_wrong_vector_dimensions_are_rejected(connection, index_id):
    with pytest.raises(psycopg.errors.DataException):
        insert_passage(connection, index_id, vector=[1.0, 0.0])


def test_same_chunk_can_exist_in_different_indexes(connection, index_id):
    another_id = uuid4().hex + uuid4().hex
    connection.execute(
        """
        INSERT INTO retrieval.indexes
            (index_id, manifest, expected_passages)
        VALUES (%s, %s::jsonb, %s)
        """,
        (another_id, "{}", 1),
    )

    insert_passage(connection, index_id)
    insert_passage(connection, another_id)

    count = connection.execute(
        """
        SELECT count(*)
        FROM retrieval.passages
        WHERE index_id IN (%s, %s)
        """,
        (index_id, another_id),
    ).fetchone()[0]

    assert count == 2
