from dataclasses import dataclass
import re

from app.retrieval.documents import KnowledgeDocument


SECTION_HEADING = re.compile(r"^##[ \t]+(.+?)\s*$")


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    document_type: str
    title: str
    section: str
    source_path: str
    synthetic: bool
    source_sha256: str
    content: str


def chunk_document(document: KnowledgeDocument) -> list[KnowledgeChunk]:
    chunks = []
    section = "Introduction"
    lines = []

    def flush():
        content = "\n".join(lines).strip()
        if not content:
            return

        # Versioned IDs prevent citations silently referring to edited text.
        chunk_id = (
            f"{document.document_id}:"
            f"{document.content_sha256}:"
            f"{len(chunks) + 1}"
        )
        chunks.append(KnowledgeChunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            document_type=document.document_type,
            title=document.title,
            section=section,
            source_path=document.source_path,
            synthetic=document.synthetic,
            source_sha256=document.content_sha256,
            content=content,
        ))

    for line in document.content.splitlines():
        heading = SECTION_HEADING.fullmatch(line)
        if heading:
            flush()
            section = heading.group(1).strip()
            lines = []
        else:
            lines.append(line)

    flush()
    return chunks
