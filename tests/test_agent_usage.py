import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import agent
from app.agent.usage import UsageCollector


def invoke(stage, usage):
    if stage == "investigation":
        return agent.choose_next_tool(
            [{"role": "user", "content": "Investigate."}],
            usage=usage,
        )

    return agent.generate_diagnosis(
        "Investigate.",
        [{
            "evidence_id": "evidence-001",
            "decision": {
                "tool": "search_logs",
                "arguments": {"service": "checkout-service", "level": "ERROR"},
            },
            "result": [],
        }],
        model="qwen3:8b",
        usage=usage,
    )


@pytest.mark.parametrize("stage", ["investigation", "diagnosis"])
def test_usage_survives_invalid_model_json(monkeypatch, stage):
    usage = UsageCollector()

    def fake_chat(**kwargs):
        return SimpleNamespace(
            message=SimpleNamespace(content="not JSON"),
            prompt_eval_count=120,
            eval_count=30,
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    with pytest.raises(ValidationError):
        invoke(stage, usage)

    assert usage.snapshot()["calls"] == [{
        "stage": stage,
        "model": "qwen3:4b" if stage == "investigation" else "qwen3:8b",
        "input_tokens": 120,
        "output_tokens": 30,
    }]


@pytest.mark.parametrize("stage", ["investigation", "diagnosis"])
def test_request_failure_records_unknown_usage_and_preserves_error(monkeypatch, stage):
    usage = UsageCollector()
    failure = RuntimeError("Model unavailable")

    def fake_chat(**kwargs):
        raise failure

    monkeypatch.setattr(agent, "chat", fake_chat)

    with pytest.raises(RuntimeError) as caught:
        invoke(stage, usage)

    assert caught.value is failure
    assert usage.snapshot()["calls"] == [{
        "stage": stage,
        "model": "qwen3:4b" if stage == "investigation" else "qwen3:8b",
        "input_tokens": None,
        "output_tokens": None,
    }]


def test_empty_evidence_does_not_record_a_model_attempt(monkeypatch):
    usage = UsageCollector()

    def unexpected_chat(**kwargs):
        pytest.fail("Empty evidence must not trigger a model request.")

    monkeypatch.setattr(agent, "chat", unexpected_chat)

    diagnosis = agent.generate_diagnosis(
        "Investigate.", [], usage=usage
    )

    assert diagnosis.status == "insufficient_evidence"
    assert usage.snapshot()["totals"]["attempts"] == 0


@pytest.mark.parametrize("second_call_fails", [False, True])
def test_investigation_accumulates_usage_through_finish_or_failure(monkeypatch, second_call_fails):
    usage = UsageCollector()
    requests = []

    def fake_chat(**kwargs):
        requests.append(kwargs)

        if len(requests) == 1:
            decision = {
                "tool": "search_logs",
                "arguments": {
                    "service": "checkout-service",
                    "level": "ERROR",
                },
                "reason": "Inspect errors.",
            }
            input_tokens, output_tokens = 100, 20
        else:
            if second_call_fails:
                raise RuntimeError("Second request failed")

            decision = {
                "tool": "finish",
                "reason": "Available evidence collected.",
            }
            input_tokens, output_tokens = 150, 10

        return SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(decision)),
            prompt_eval_count=input_tokens,
            eval_count=output_tokens,
        )

    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setattr(
        agent,
        "execute_tool",
        lambda decision, *, data_dir: [],
    )

    if second_call_fails:
        with pytest.raises(RuntimeError, match="Second request failed"):
            agent.investigate("Investigate.", usage=usage)
    else:
        result = agent.investigate("Investigate.", usage=usage)
        assert result["status"] == "finished"
        assert len(result["steps"]) == 1

    snapshot = usage.snapshot()
    totals = snapshot["totals"]

    assert len(requests) == 2
    assert totals["attempts"] == 2
    assert [call["stage"] for call in snapshot["calls"]] == [
        "investigation", "investigation"
    ]

    if second_call_fails:
        assert totals["input_tokens"] is None
        assert totals["output_tokens"] is None
        assert totals["known_input_tokens"] == 100
        assert totals["known_output_tokens"] == 20
    else:
        assert totals["input_tokens"] == 250
        assert totals["output_tokens"] == 30
