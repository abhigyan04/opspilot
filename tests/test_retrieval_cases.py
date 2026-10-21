from app.retrieval.chunks import chunk_document
from app.retrieval.documents import load_documents
from evals.retrieval_cases import RETRIEVAL_CASES


def test_retrieval_case_ids_and_queries_are_unique():
    cases = RETRIEVAL_CASES

    assert len({case.case_id for case in cases}) == len(cases)
    assert len({case.query for case in cases}) == len(cases)
    assert all(case.case_id.strip() and case.query.strip() for case in cases)


def test_expected_sections_exist_and_are_unambiguous():
    chunks = [
        chunk
        for document in load_documents()
        for chunk in chunk_document(document)
    ]
    section_keys = [
        (chunk.document_id, chunk.section)
        for chunk in chunks
    ]

    for case in RETRIEVAL_CASES:
        for expected in case.relevant_sections:
            assert section_keys.count(expected) == 1, (
                case.case_id,
                expected,
            )


def test_cases_include_answerable_and_unanswerable_queries():
    positive = [
        case for case in RETRIEVAL_CASES
        if case.relevant_sections
    ]
    negative = [
        case for case in RETRIEVAL_CASES
        if not case.relevant_sections
    ]

    assert len(positive) == 6
    assert len(negative) == 2


def test_positive_cases_cover_all_reference_documents():
    covered_documents = {
        document_id
        for case in RETRIEVAL_CASES
        for document_id, section in case.relevant_sections
    }

    assert covered_documents == {
        document.document_id
        for document in load_documents()
    }
