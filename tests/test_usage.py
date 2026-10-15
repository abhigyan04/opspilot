from types import SimpleNamespace

import pytest

from app.agent.usage import UsageCollector


def test_usage_sums_reported_counts_and_preserves_call_identity():
    usage = UsageCollector()
    usage.record(
        stage="investigation",
        model="qwen3:4b",
        response=SimpleNamespace(prompt_eval_count=100, eval_count=20),
    )
    usage.record(
        stage="diagnosis",
        model="qwen3:8b",
        response=SimpleNamespace(prompt_eval_count=200, eval_count=40),
    )

    result = usage.snapshot()

    assert result["calls"] == [
        {
            "stage": "investigation",
            "model": "qwen3:4b",
            "input_tokens": 100,
            "output_tokens": 20,
        },
        {
            "stage": "diagnosis",
            "model": "qwen3:8b",
            "input_tokens": 200,
            "output_tokens": 40,
        },
    ]
    assert result["totals"] == {
        "attempts": 2,
        "input_counted_calls": 2,
        "known_input_tokens": 300,
        "input_tokens": 300,
        "output_counted_calls": 2,
        "known_output_tokens": 60,
        "output_tokens": 60,
    }


def test_missing_output_count_does_not_become_zero():
    usage = UsageCollector()
    usage.record(
        stage="diagnosis",
        model="qwen3:8b",
        response=SimpleNamespace(prompt_eval_count=100),
    )

    totals = usage.snapshot()["totals"]

    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] is None
    assert totals["output_counted_calls"] == 0
    assert totals["known_output_tokens"] == 0


def test_attempt_without_response_preserves_known_subtotals():
    usage = UsageCollector()
    usage.record(
        stage="investigation",
        model="qwen3:4b",
        response=SimpleNamespace(prompt_eval_count=100, eval_count=20),
    )
    usage.record(stage="diagnosis", model="qwen3:8b")

    totals = usage.snapshot()["totals"]

    assert totals["attempts"] == 2
    assert totals["input_tokens"] is None
    assert totals["output_tokens"] is None
    assert totals["known_input_tokens"] == 100
    assert totals["known_output_tokens"] == 20


@pytest.mark.parametrize("invalid", [-1, True, 1.5, "10"])
def test_invalid_counts_are_unknown(invalid):
    usage = UsageCollector()
    usage.record(
        stage="diagnosis",
        model="qwen3:8b",
        response=SimpleNamespace(
            prompt_eval_count=invalid,
            eval_count=invalid,
        ),
    )

    totals = usage.snapshot()["totals"]

    assert totals["input_tokens"] is None
    assert totals["output_tokens"] is None


def test_zero_counts_are_valid():
    usage = UsageCollector()
    usage.record(
        stage="diagnosis",
        model="qwen3:8b",
        response=SimpleNamespace(prompt_eval_count=0, eval_count=0),
    )

    totals = usage.snapshot()["totals"]

    assert totals["input_tokens"] == 0
    assert totals["output_tokens"] == 0
    assert totals["input_counted_calls"] == 1
    assert totals["output_counted_calls"] == 1


def test_empty_collector_and_snapshot_isolation():
    usage = UsageCollector()

    empty = usage.snapshot()
    assert empty["totals"]["attempts"] == 0
    assert empty["totals"]["input_tokens"] == 0
    assert empty["totals"]["output_tokens"] == 0

    usage.record(stage="diagnosis", model="qwen3:8b")
    snapshot = usage.snapshot()
    snapshot["calls"][0]["model"] = "modified"

    assert usage.snapshot()["calls"][0]["model"] == "qwen3:8b"
