from hashlib import sha256

from app.retrieval.chunks import chunk_document
from app.retrieval.documents import KnowledgeDocument, load_documents


def make_document(content):
    return KnowledgeDocument(
        document_id="runbook-example",
        document_type="runbook",
        title="Example",
        source_path="runbooks/example.md",
        synthetic=True,
        content=content,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
    )


def test_splits_sections_and_preserves_introduction():
    document = make_document(
        "# Example\n\nSynthetic reference.\n\n"
        "## Symptoms\n\nTimeouts occur.\n\n"
        "## Investigation\n\nCheck dependency metrics.\n"
    )

    chunks = chunk_document(document)

    assert [chunk.section for chunk in chunks] == [
        "Introduction", "Symptoms", "Investigation",
    ]
    assert [chunk.content for chunk in chunks] == [
        "# Example\n\nSynthetic reference.",
        "Timeouts occur.",
        "Check dependency metrics.",
    ]


def test_preserves_source_metadata():
    document = make_document("## Symptoms\nTimeouts occur.")
    chunk, = chunk_document(document)

    assert chunk.document_id == document.document_id
    assert chunk.document_type == "runbook"
    assert chunk.title == "Example"
    assert chunk.source_path == document.source_path
    assert chunk.synthetic is True
    assert chunk.source_sha256 == document.content_sha256


def test_ids_are_deterministic_and_unique_for_repeated_sections():
    document = make_document(
        "## Checks\nFirst check.\n"
        "## Checks\nSecond check.\n"
    )

    first = chunk_document(document)
    second = chunk_document(document)

    assert first == second
    assert len({chunk.chunk_id for chunk in first}) == 2


def test_document_edit_changes_citation_ids():
    before = chunk_document(make_document("## Checks\nOld guidance."))
    after = chunk_document(make_document("## Checks\nNew guidance."))

    assert before[0].chunk_id != after[0].chunk_id


def test_skips_empty_sections():
    document = make_document(
        "## Empty\n\n## Useful\nCheck logs.\n\n## Also empty\n"
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    assert chunks[0].section == "Useful"
    assert chunks[0].content == "Check logs."


def test_keeps_subheadings_inside_their_section():
    document = make_document(
        "## Investigation\n"
        "### Timing\nCompare timestamps.\n"
        "### Scope\nCompare affected versions.\n"
    )

    chunk, = chunk_document(document)

    assert chunk.section == "Investigation"
    assert "### Timing" in chunk.content
    assert "### Scope" in chunk.content


def test_repository_documents_produce_citable_chunks():
    documents = load_documents()
    chunks = [
        chunk
        for document in documents
        for chunk in chunk_document(document)
    ]

    assert {chunk.document_id for chunk in chunks} == {
        document.document_id for document in documents
    }
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert all(chunk.content.strip() for chunk in chunks)
    assert all(chunk.synthetic for chunk in chunks)
