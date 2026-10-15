from copy import deepcopy

from app.agent.evidence import build_evidence_timeline


def make_step(evidence_id, tool, records):
    return {
        "evidence_id": evidence_id,
        "decision": {"tool": tool},
        "result": records,
    }


def test_timeline_orders_by_instant_across_timezones():
    steps = [
        make_step("deployment", "get_deployments", [{
            "timestamp": "2026-09-28T13:57:00Z",
            "version": "1.7.4",
        }]),
        make_step("logs", "search_logs", [{
            "timestamp": "2026-09-28T19:24:00+05:30",
            "message": "Payment authorization failed",
        }]),
        make_step("metrics", "query_metrics", [{
            "timestamp": "2026-09-28T13:50:00Z",
            "value": 0.01,
        }]),
    ]

    timeline = build_evidence_timeline(steps)

    assert [event["evidence_id"] for event in timeline] == [
        "metrics", "logs", "deployment"
    ]
    assert timeline[1]["record"] == steps[1]["result"][0]


def test_timeline_does_not_mutate_or_share_source_records():
    steps = [make_step("logs", "search_logs", [{
        "timestamp": "2026-09-28T13:54:00Z",
        "message": "Original",
    }])]
    original = deepcopy(steps)

    timeline = build_evidence_timeline(steps)
    timeline[0]["record"]["message"] = "Changed"

    assert steps == original


def test_timeline_leaves_unusable_timestamps_in_original_observations():
    steps = [make_step("logs", "search_logs", [
        {"message": "No timestamp"},
        {"timestamp": "invalid"},
        {"timestamp": "2026-09-28T13:54:00"},
        {"timestamp": None},
    ])]
    original = deepcopy(steps)

    assert build_evidence_timeline(steps) == []
    assert steps == original
