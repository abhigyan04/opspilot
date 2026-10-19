import json
from hashlib import sha256

import pytest

from app.retrieval.documents import load_documents


def make_collection(tmp_path, **overrides):
    entry = {
        "document_id": "runbook-example",
        "document_type": "runbook",
        "title": "Example runbook",
        "path": "example.md",
        "synthetic": True,
        **overrides,
    }
    catalog = {
        "schema_version": 1,
        "documents": [entry],
    }
    (tmp_path / "example.md").write_text(
        "# Example\n\nCheck current observations.\n",
        encoding="utf-8",
    )
    write_catalog(tmp_path, catalog)
    return catalog


def write_catalog(directory, catalog):
    (directory / "catalog.json").write_text(
        json.dumps(catalog),
        encoding="utf-8",
    )


def test_loads_document_and_hashes_exact_bytes(tmp_path):
    make_collection(tmp_path)

    document, = load_documents(tmp_path)
    raw = (tmp_path / "example.md").read_bytes()

    assert document.document_id == "runbook-example"
    assert document.source_path == "example.md"
    assert document.synthetic is True
    assert document.content == raw.decode("utf-8")
    assert document.content_sha256 == sha256(raw).hexdigest()


def test_loads_repository_collection():
    documents = load_documents()

    assert {document.document_id for document in documents} == {
        "runbook-dependency-errors",
        "runbook-application-exceptions",
        "incident-inventory-timeout",
    }
    assert all(document.synthetic for document in documents)


def test_rejects_duplicate_ids(tmp_path):
    catalog = make_collection(tmp_path)
    catalog["documents"].append(dict(catalog["documents"][0]))
    write_catalog(tmp_path, catalog)

    with pytest.raises(ValueError, match="Duplicate document ID"):
        load_documents(tmp_path)


def test_rejects_same_file_under_different_ids(tmp_path):
    catalog = make_collection(tmp_path)
    catalog["documents"].append({
        **catalog["documents"][0],
        "document_id": "another-document",
    })
    write_catalog(tmp_path, catalog)

    with pytest.raises(ValueError, match="Duplicate document path"):
        load_documents(tmp_path)


@pytest.mark.parametrize("path", [
    "../outside.md",
    "/outside.md",
    "C:/outside.md",
    r"..\outside.md",
    "example.txt",
])
def test_rejects_invalid_paths(tmp_path, path):
    make_collection(tmp_path, path=path)

    with pytest.raises(ValueError, match="Invalid document path"):
        load_documents(tmp_path)


def test_missing_document_is_not_silently_skipped(tmp_path):
    make_collection(tmp_path, path="missing.md")

    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path)


def test_rejects_empty_document(tmp_path):
    make_collection(tmp_path)
    (tmp_path / "example.md").write_text(" \n", encoding="utf-8")

    with pytest.raises(ValueError, match="Document is empty"):
        load_documents(tmp_path)


@pytest.mark.parametrize("overrides", [
    {"title": "   "},
    {"document_type": "unknown"},
    {"synthetic": "true"},
    {"document_id": "Invalid ID"},
])
def test_rejects_invalid_metadata(tmp_path, overrides):
    make_collection(tmp_path, **overrides)

    with pytest.raises(ValueError):
        load_documents(tmp_path)


def test_rejects_unsupported_catalog_version(tmp_path):
    catalog = make_collection(tmp_path)
    catalog["schema_version"] = 2
    write_catalog(tmp_path, catalog)

    with pytest.raises(ValueError):
        load_documents(tmp_path)
