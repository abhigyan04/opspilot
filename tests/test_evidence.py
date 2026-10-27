from copy import deepcopy
import pytest

from app.agent.evidence import (
    build_evidence_timeline, build_deployment_timing, build_deployment_metric_timing,
)


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


def test_metric_timing_uses_deployment_not_previous_sample():
    steps = [
        make_step("deploy", "get_deployments", [{
            "service": "checkout", "timestamp": "2026-09-28T13:57:00Z",
        }]),
        make_step("metrics", "query_metrics", [
            {"service": "checkout", "metric": "error_rate", "value": value,
             "timestamp": timestamp}
            for timestamp, value in [
                ("2026-09-28T13:55:00Z", 0.01),
                ("2026-09-28T14:02:00Z", 0.35),
                ("2026-09-28T14:05:00Z", 0.4),
            ]
        ]),
    ]
    original = deepcopy(steps)
    result = build_deployment_metric_timing(steps)
    assert [(x["value"], x["seconds_after_deployment"]) for x in result] == [
        (0.01, -120), (0.35, 300), (0.4, 480),
    ]
    assert result[-1] == {
        "service": "checkout", "deployment_evidence_id": "deploy",
        "deployment_timestamp": "2026-09-28T13:57:00Z",
        "metric_evidence_id": "metrics", "sample_timestamp": "2026-09-28T14:05:00Z",
        "metric": "error_rate", "value": 0.4,
        "seconds_after_deployment": 480, "minutes_after_deployment": 8,
    }
    assert steps == original


def test_metric_timing_handles_offsets_and_multiple_deployments():
    steps = [make_step("deploy", "get_deployments", [
        {"service": "checkout", "timestamp": timestamp}
        for timestamp in ("2026-09-28T13:57:00Z", "2026-09-28T14:00:00Z")
    ]), make_step("metrics", "query_metrics", [{
        "service": "checkout", "timestamp": "2026-09-28T19:27:00+05:30",
        "metric": "error_rate", "value": 0,
    }])]
    assert [r["seconds_after_deployment"] for r in build_deployment_metric_timing(steps)] == [0, -180]


@pytest.mark.parametrize("changes", [
    {"service": "another-service"}, {"timestamp": "bad"},
    {"timestamp": "2026-09-28T14:05:00"}, {"metric": ""},
    {"value": True}, {"value": None}, {"value": float("nan")},
    {"value": float("inf")},
])
def test_metric_timing_skips_unusable_samples(changes):
    sample = {"service": "checkout", "timestamp": "2026-09-28T14:05:00Z",
              "metric": "error_rate", "value": 0.4, **changes}
    steps = [make_step("deploy", "get_deployments", [{
        "service": "checkout", "timestamp": "2026-09-28T13:57:00Z",
    }]), make_step("metrics", "query_metrics", [sample])]
    assert build_deployment_metric_timing(steps) == []


def test_metric_timing_requires_a_deployment_and_metric_pair():
    assert build_deployment_metric_timing([]) == []
    assert build_deployment_metric_timing([make_step("logs", "search_logs", [{
        "service": "checkout", "timestamp": "2026-09-28T14:05:00Z",
        "metric": "error_rate", "value": 0.4,
    }])]) == []
