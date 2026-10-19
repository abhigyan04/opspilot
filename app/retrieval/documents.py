from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_KNOWLEDGE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "knowledge"
)


class DocumentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    document_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    document_type: Literal["runbook", "historical_incident"]
    title: str = Field(min_length=1)
    path: str = Field(min_length=1)
    synthetic: bool


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    documents: list[DocumentEntry] = Field(min_length=1)


@dataclass(frozen=True)
class KnowledgeDocument:
    document_id: str
    document_type: str
    title: str
    source_path: str
    synthetic: bool
    content: str
    content_sha256: str


def load_documents(knowledge_dir: Path = DEFAULT_KNOWLEDGE_DIR) -> list[KnowledgeDocument]:
    root = knowledge_dir.resolve()
    catalog = Catalog.model_validate_json(
        (root / "catalog.json").read_text(encoding="utf-8")
    )

    documents = []
    seen_ids = set()
    seen_paths = set()

    for entry in catalog.documents:
        if entry.document_id in seen_ids:
            raise ValueError(f"Duplicate document ID: {entry.document_id}")
        seen_ids.add(entry.document_id)

        if not entry.title.strip():
            raise ValueError("Document title must not be blank.")

        # Catalog paths use portable, relative forward-slash notation.
        relative = PurePosixPath(entry.path)
        if (
            relative.is_absolute()
            or "\\" in entry.path
            or ":" in entry.path
            or ".." in relative.parts
            or relative.suffix != ".md"
        ):
            raise ValueError(f"Invalid document path: {entry.path}")

        source = root.joinpath(*relative.parts).resolve()

        # Also protects against a symlink pointing outside the collection.
        if not source.is_relative_to(root):
            raise ValueError(f"Document path escapes knowledge directory: {entry.path}")

        if source in seen_paths:
            raise ValueError(f"Duplicate document path: {entry.path}")
        seen_paths.add(source)

        raw = source.read_bytes()
        content = raw.decode("utf-8")
        if not content.strip():
            raise ValueError(f"Document is empty: {entry.path}")

        documents.append(KnowledgeDocument(
            document_id=entry.document_id,
            document_type=entry.document_type,
            title=entry.title,
            source_path=relative.as_posix(),
            synthetic=entry.synthetic,
            content=content,
            content_sha256=sha256(raw).hexdigest(),
        ))

    return documents
