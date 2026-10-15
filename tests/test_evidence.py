from copy import deepcopy
import pytest

from app.agent.evidence import build_evidence_timeline, build_deployment_timing


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


@pytest.mark.parametrize("timestamp, relation", [
    ("2026-09-28T19:24:00+05:30", "before"),
    ("2026-09-28T19:27:00+05:30", "same_time"),
    ("2026-09-28T19:32:00+05:30", "after"),
])
def test_deployment_timing_compares_earliest_matching_error(
    timestamp, relation
):
    steps = [
        make_step("deployment", "get_deployments", [{
            "service": "checkout-service",
            "timestamp": "2026-09-28T13:57:00Z",
        }]),
        make_step("logs", "search_logs", [
            {
                "service": "checkout-service",
                "level": "ERROR",
                "timestamp": "2026-09-28T15:00:00Z",
                "message": "Later failure",
            },
            {
                "service": "another-service",
                "level": "ERROR",
                "timestamp": "2026-09-28T12:00:00Z",
                "message": "Unrelated service",
            },
            {
                "service": "checkout-service",
                "level": "INFO",
                "timestamp": "2026-09-28T12:00:00Z",
                "message": "Informational event",
            },
            {
                "service": "checkout-service",
                "level": "ERROR",
                "timestamp": timestamp,
                "message": "Selected failure",
            },
        ]),
    ]
    original = deepcopy(steps)

    result = build_deployment_timing(steps)

    assert len(result) == 1
    assert result[0]["error_relative_to_deployment"] == relation
    assert result[0]["earliest_observed_error"] == {
        "evidence_id": "logs",
        "tool": "search_logs",
        "record": steps[1]["result"][3],
    }
    assert result[0]["deployment"]["evidence_id"] == "deployment"
    assert steps == original


@pytest.mark.parametrize("timestamp", [
    None,
    "invalid",
    "2026-09-28T13:54:00",
])
def test_deployment_timing_requires_usable_error_timestamp(timestamp):
    steps = [
        make_step("deployment", "get_deployments", [{
            "service": "checkout-service",
            "timestamp": "2026-09-28T13:57:00Z",
        }]),
        make_step("logs", "search_logs", [{
            "service": "checkout-service",
            "level": "ERROR",
            "timestamp": timestamp,
        }]),
    ]

    assert build_deployment_timing(steps) == []
