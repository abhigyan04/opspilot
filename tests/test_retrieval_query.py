from copy import deepcopy

import pytest

from app.retrieval.query import (
    MAX_INCIDENT_CHARS,
    MAX_MESSAGE_CHARS,
    MAX_MESSAGES,
    build_retrieval_query,
)


def log_step(records, level="ERROR"):
    return {
        "decision": {
            "tool": "search_logs",
            "arguments": {"level": level},
            "reason": "UNSUPPORTED MODEL REASONING",
        },
        "result": records,
    }


def test_query_uses_distinct_observed_errors_without_model_reasoning():
    message = "Payment authorization failed: PayBridge returned HTTP 503."
    steps = [log_step([
        {"level": "ERROR", "message": message},
        {"level": "ERROR", "message": message},
    ])]
    original = deepcopy(steps)

    query = build_retrieval_query("Checkout errors increased.", steps)

    assert query == message
    assert "UNSUPPORTED MODEL REASONING" not in query
    assert steps == original


def test_query_ignores_non_log_results_and_non_error_records():
    steps = [
        {
            "decision": {"tool": "get_commit"},
            "result": {"message": "COMMIT MESSAGE"},
        },
        log_step([
            {"level": "INFO", "message": "INFO MESSAGE"},
            {"level": "CRITICAL", "message": "Dependency unavailable."},
        ]),
    ]

    assert build_retrieval_query("Investigate.", steps) == (
        "Dependency unavailable."
    )


def test_query_uses_requested_level_when_record_omits_level():
    steps = [log_step([{"message": "Request failed."}])]

    assert build_retrieval_query("Investigate.", steps).endswith(
        "Request failed."
    )


def test_query_without_usable_messages_contains_only_incident():
    steps = [
        log_step([{}, None, {"message": " "}, {"message": 42}]),
        log_step({"message": "Unexpected result shape"}),
    ]

    assert build_retrieval_query("  Investigate.\n", steps) == (
        "Investigate."
    )


def test_query_bounds_message_lengths_and_count():
    steps = [log_step([
        {"message": f"{number} " + "x" * 500}
        for number in range(10)
    ])]

    lines = build_retrieval_query("i" * 800, steps).splitlines()

    assert len(lines) == MAX_MESSAGES
    assert all(len(line) == MAX_MESSAGE_CHARS for line in lines)
    assert [line.split()[0] for line in lines] == ["0", "1", "2"]


def test_incident_fallback_is_bounded_and_has_no_label():
    assert build_retrieval_query("i" * 800, []) == (
        "i" * MAX_INCIDENT_CHARS
    )


def test_query_normalizes_whitespace_before_deduplication():
    steps = [log_step([
        {"message": "Payment\n failed."},
        {"message": "Payment   failed."},
    ])]

    assert build_retrieval_query("Checkout\n errors.", steps) == (
        "Payment failed."
    )


@pytest.mark.parametrize("incident", ["", " \n ", None])
def test_query_rejects_blank_or_invalid_incident(incident):
    with pytest.raises(ValueError, match="nonblank"):
        build_retrieval_query(incident, [])
