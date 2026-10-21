from copy import deepcopy
from dataclasses import replace

import pytest

from app.retrieval import chunks as chunking
from app.retrieval.chunks import chunk_document
from app.retrieval.documents import load_documents
from app.retrieval.provenance import (
    build_manifest,
    manifest_fingerprint,
)


@pytest.fixture
def passages():
    return chunk_document(load_documents()[0])


@pytest.fixture
def identity():
    return {
        "model": "embeddinggemma:300m",
        "digest": "a" * 64,
        "dimensions": 768,
        "format_version": 1,
    }


def test_identical_inputs_produce_identical_fingerprints(passages, identity):
    first = build_manifest(passages, identity)
    second = build_manifest(passages, identity)

    assert manifest_fingerprint(first) == manifest_fingerprint(second)


def test_dictionary_key_order_does_not_change_fingerprint(passages, identity):
    manifest = build_manifest(passages, identity)
    reordered = dict(reversed(list(manifest.items())))

    assert manifest_fingerprint(manifest) == manifest_fingerprint(reordered)


@pytest.mark.parametrize("field,value", [
    ("digest", "b" * 64),
    ("model", "another-model:latest"),
    ("dimensions", 384),
    ("format_version", 2),
])
def test_embedding_identity_changes_invalidate_manifest(passages, identity, field, value):
    before = build_manifest(passages, identity)
    changed = {**identity, field: value}
    after = build_manifest(passages, changed)

    assert manifest_fingerprint(before) != manifest_fingerprint(after)


@pytest.mark.parametrize("field,value", [
    ("title", "Changed catalog title"),
    ("section", "Changed section"),
    ("content", "Changed passage text"),
    ("source_sha256", "b" * 64),
    ("synthetic", False),
])
def test_passage_changes_invalidate_manifest(passages, identity, field, value):
    changed = [
        replace(passages[0], **{field: value}),
        *passages[1:],
    ]

    assert manifest_fingerprint(
        build_manifest(passages, identity)
    ) != manifest_fingerprint(
        build_manifest(changed, identity)
    )


def test_passage_order_changes_invalidate_manifest(passages, identity):
    assert manifest_fingerprint(
        build_manifest(passages, identity)
    ) != manifest_fingerprint(
        build_manifest(list(reversed(passages)), identity)
    )


def test_chunking_version_changes_invalidate_manifest(passages, identity, monkeypatch):
    before = build_manifest(passages, identity)

    monkeypatch.setattr(
        chunking, "CHUNKING_VERSION", chunking.CHUNKING_VERSION + 1
    )
    after = build_manifest(passages, identity)

    assert manifest_fingerprint(before) != manifest_fingerprint(after)


def test_manifest_does_not_retain_mutable_identity_reference(passages, identity):
    manifest = build_manifest(passages, identity)
    original = deepcopy(manifest)

    identity["digest"] = "b" * 64

    assert manifest == original


def test_empty_collection_is_rejected(identity):
    with pytest.raises(ValueError, match="without passages"):
        build_manifest([], identity)


def test_duplicate_chunk_ids_are_rejected(passages, identity):
    with pytest.raises(ValueError, match="unique"):
        build_manifest([passages[0], passages[0]], identity)
