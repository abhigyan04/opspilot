import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.retrieval import chunks as chunking
from app.retrieval import documents, embeddings, search
from evals import retrieval_cases, retrieval_evaluator
from evals.runner import save_report


def run_evaluation(*, top_k: int = 3) -> dict:
    if type(top_k) is not int or top_k < 1:
        raise ValueError("top_k must be a positive integer.")

    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()

    loaded = documents.load_documents()
    chunks = [
        chunk
        for document in loaded
        for chunk in chunking.chunk_document(document)
    ]
    if not chunks:
        raise ValueError("No passages available for evaluation.")

    cases = retrieval_cases.RETRIEVAL_CASES
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Evaluation cases must be nonempty with unique IDs.")

    # Embed the collection once, not once per query.
    vectors = embeddings.embed_chunks(chunks)
    results = []

    for case in cases:
        query_vector = embeddings.embed_query(case.query)
        hits = search.rank_chunks(
            query_vector,
            chunks,
            vectors,
            top_k=top_k,
        )
        results.append(
            retrieval_evaluator.evaluate_retrieval(
                case, hits, top_k=top_k
            )
        )

    positive = [
        result for result in results
        if result["case_type"] == "positive"
    ]
    negative = [
        result for result in results
        if result["case_type"] == "negative"
    ]

    def mean_positive(field):
        if not positive:
            return None
        return sum(result[field] for result in positive) / len(positive)

    code_files = {
        "documents": Path(documents.__file__),
        "chunking": Path(chunking.__file__),
        "embeddings": Path(embeddings.__file__),
        "search": Path(search.__file__),
        "cases": Path(retrieval_cases.__file__),
        "evaluator": Path(retrieval_evaluator.__file__),
        "runner": Path(__file__),
    }

    return {
        "report_version": 1,
        "run_id": str(uuid4()),
        "evaluation_mode": "retrieval_development",
        "status": "completed",
        "started_at": started_at,
        "total_seconds": perf_counter() - started,
        "embedding_model": embeddings.EMBEDDING_MODEL,
        "embedding_dimensions": embeddings.EMBEDDING_DIMENSIONS,
        "embedding_format_version": embeddings.EMBEDDING_FORMAT_VERSION,
        "top_k": top_k,
        "code_sha256": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in code_files.items()
        },
        "documents": [
            {
                "document_id": document.document_id,
                "source_path": document.source_path,
                "content_sha256": document.content_sha256,
            }
            for document in loaded
        ],
        "chunks": [asdict(chunk) for chunk in chunks],
        "summary": {
            "total_cases": len(results),
            "positive_cases": len(positive),
            "negative_cases": len(negative),
            "hit_rate_at_k": mean_positive("hit_at_k"),
            "mean_recall_at_k": mean_positive("recall_at_k"),
            "mean_reciprocal_rank_at_k": mean_positive(
                "reciprocal_rank_at_k"
            ),
            "negative_cases_with_results": sum(
                result["returned_for_negative"] for result in negative
            ),
        },
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate local retrieval on the development query set."
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "out" / "retrieval",
    )
    args = parser.parse_args(argv)

    report = run_evaluation(top_k=args.top_k)
    destination = save_report(report, args.output_dir)

    print(json.dumps({
        "report_path": str(destination.resolve()),
        "status": report["status"],
        "top_k": report["top_k"],
        "summary": report["summary"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
