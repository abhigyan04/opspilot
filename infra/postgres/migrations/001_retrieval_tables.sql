BEGIN;

CREATE SCHEMA IF NOT EXISTS retrieval;

CREATE TABLE retrieval.indexes (
    index_id text PRIMARY KEY
        CHECK (index_id ~ '^[0-9a-f]{64}$'),

    manifest jsonb NOT NULL
        CHECK (jsonb_typeof(manifest) = 'object'),

    expected_passages integer NOT NULL
        CHECK (expected_passages > 0),

    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE retrieval.passages (
    index_id text NOT NULL
        REFERENCES retrieval.indexes(index_id),

    chunk_id text NOT NULL
        CHECK (length(btrim(chunk_id)) > 0),

    position integer NOT NULL
        CHECK (position >= 0),

    document_id text NOT NULL
        CHECK (length(btrim(document_id)) > 0),

    document_type text NOT NULL
        CHECK (document_type IN ('runbook', 'historical_incident')),

    title text NOT NULL
        CHECK (length(btrim(title)) > 0),

    section text NOT NULL
        CHECK (length(btrim(section)) > 0),

    source_path text NOT NULL
        CHECK (length(btrim(source_path)) > 0),

    synthetic boolean NOT NULL,

    source_sha256 text NOT NULL
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),

    content text NOT NULL
        CHECK (length(btrim(content)) > 0),

    embedding vector(768) NOT NULL
        CHECK (vector_norm(embedding) > 0),

    PRIMARY KEY (index_id, chunk_id),
    UNIQUE (index_id, position)
);

COMMIT;
