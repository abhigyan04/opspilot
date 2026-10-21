import json

import pytest

from evals import retrieval_runner
from evals.retrieval_cases import RetrievalCase


@pytest.fixture
def fake_embeddings(monkeypatch):
    calls = {"collections": 0, "queries": []}

    def embed_chunks(chunks):
        calls["collections"] += 1
        return [[1.0, 0.0] for _ in chunks]

    def embed_query(query):
        calls["queries"].append(query)
        return [1.0, 0.0]

    monkeypatch.setattr(
        retrieval_runner.embeddings, "embed_chunks", embed_chunks
    )
    monkeypatch.setattr(
        retrieval_runner.embeddings, "embed_query", embed_query
    )
    return calls


def test_embeds_collection_once_and_runs_each_query(fake_embeddings):
    report = retrieval_runner.run_evaluation()

    assert fake_embeddings["collections"] == 1
    assert fake_embeddings["queries"] == [
        case.query
        for case in retrieval_runner.retrieval_cases.RETRIEVAL_CASES
    ]
    assert report["status"] == "completed"
    assert report["summary"]["total_cases"] == 8
    assert report["summary"]["positive_cases"] == 6
    assert report["summary"]["negative_cases"] == 2
    assert report["summary"]["negative_cases_with_results"] == 2
    assert len(report["chunks"]) == 14


def test_negatives_are_excluded_from_positive_averages(monkeypatch, fake_embeddings):
    chunks = [
        chunk
        for document in retrieval_runner.documents.load_documents()
        for chunk in retrieval_runner.chunking.chunk_document(document)
    ]
    # All fake vectors tie, so the smallest chunk ID ranks first.
    first = min(chunks, key=lambda chunk: chunk.chunk_id)

    cases = (
        RetrievalCase(
            case_id="positive",
            query="Find a reference.",
            relevant_sections=frozenset({
                (first.document_id, first.section),
            }),
        ),
        RetrievalCase(
            case_id="negative",
            query="Unanswerable query.",
            relevant_sections=frozenset(),
        ),
    )
    monkeypatch.setattr(
        retrieval_runner.retrieval_cases, "RETRIEVAL_CASES", cases
    )

    summary = retrieval_runner.run_evaluation(top_k=1)["summary"]

    assert summary["hit_rate_at_k"] == 1.0
    assert summary["mean_recall_at_k"] == 1.0
    assert summary["mean_reciprocal_rank_at_k"] == 1.0
    assert summary["negative_cases_with_results"] == 1


def test_cli_saves_report(tmp_path, capsys, fake_embeddings):
    exit_code = retrieval_runner.main([
        "--output-dir", str(tmp_path),
        "--top-k", "2",
    ])

    output = json.loads(capsys.readouterr().out)
    reports = list(tmp_path.glob("*.json"))

    assert exit_code == 0
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["summary"] == output["summary"]
    assert report["top_k"] == 2
    assert all(
        result["returned_count"] == 2
        for result in report["results"]
    )


def test_invalid_top_k_fails_before_embedding(fake_embeddings):
    with pytest.raises(ValueError, match="top_k"):
        retrieval_runner.run_evaluation(top_k=0)

    assert fake_embeddings["collections"] == 0


def test_embedding_failure_does_not_save_completed_report(tmp_path, monkeypatch):
    def fail(chunks):
        raise ConnectionError("Ollama unavailable")

    monkeypatch.setattr(
        retrieval_runner.embeddings, "embed_chunks", fail
    )

    with pytest.raises(ConnectionError):
        retrieval_runner.main(["--output-dir", str(tmp_path)])

    assert list(tmp_path.iterdir()) == []
