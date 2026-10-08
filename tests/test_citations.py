import pytest

from evals.citations import build_citation_view


def make_report():
    return {
        "diagnosis": {
            "status": "supported",
            "root_cause": {
                "statement": "Provider errors caused payment failures.",
                "evidence_ids": ["evidence-002"],
            },
            "supporting_claims": [{
                "statement": "The error rate increased.",
                "evidence_ids": ["evidence-001"],
            }],
        },
        "investigation": {
            "steps": [
                {
                    "evidence_id": "evidence-001",
                    "decision": {
                        "tool": "query_metrics",
                        "arguments": {"service": "checkout-service"},
                        "reason": "MODEL REASONING IS NOT EVIDENCE",
                    },
                    "result": [{"value": 0.4}],
                },
                {
                    "evidence_id": "evidence-002",
                    "decision": {
                        "tool": "search_logs",
                        "arguments": {"service": "checkout-service"},
                        "reason": "MODEL REASONING IS NOT EVIDENCE",
                    },
                    "result": [{"message": "Provider returned HTTP 503"}],
                },
            ],
        },
    }


def test_citations_resolve_by_id_not_step_position():
    view = build_citation_view(make_report())

    assert view[0]["claim_path"] == "root_cause"
    assert view[0]["cited_observations"] == [{
        "evidence_id": "evidence-002",
        "tool": "search_logs",
        "arguments": {"service": "checkout-service"},
        "result": [{"message": "Provider returned HTTP 503"}],
    }]
    assert view[1]["cited_observations"][0]["tool"] == "query_metrics"
    assert "MODEL REASONING" not in str(view)


def test_unknown_citation_is_visible_without_substituting_evidence():
    report = make_report()
    report["diagnosis"]["root_cause"]["evidence_ids"] = ["unknown"]

    root = build_citation_view(report)[0]

    assert root["missing_evidence_ids"] == ["unknown"]
    assert root["cited_observations"] == []


def test_duplicate_observation_ids_are_rejected():
    report = make_report()
    steps = report["investigation"]["steps"]
    steps[1]["evidence_id"] = steps[0]["evidence_id"]

    with pytest.raises(ValueError, match="Duplicate evidence ID"):
        build_citation_view(report)


@pytest.mark.parametrize("diagnosis", [
    None,
    {"status": "insufficient_evidence"},
])
def test_no_citation_view_when_there_are_no_structured_claims(diagnosis):
    assert build_citation_view({"diagnosis": diagnosis}) == []
