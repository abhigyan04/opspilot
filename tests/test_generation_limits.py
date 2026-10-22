import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agent import agent
from app.agent.settings import DiagnosisSettings
from app.agent.usage import UsageCollector


def steps():
    return [{
        "evidence_id": "evidence-001",
        "decision": {
            "tool": "search_logs",
            "arguments": {"service": "checkout-service", "level": "ERROR"},
        },
        "result": [],
    }]


def insufficient_json():
    return json.dumps({
        "status": "insufficient_evidence",
        "reason": "No matching errors were returned.",
        "missing_evidence": ["Failure details"],
    })


@pytest.mark.parametrize("settings, expected_limit", [
    (None, 2048),
    (DiagnosisSettings(num_predict=512), 512),
])
def test_diagnosis_always_sends_generation_limit(monkeypatch, settings, expected_limit):
    def fake_chat(**kwargs):
        assert kwargs["options"]["num_predict"] == expected_limit
        return SimpleNamespace(
            done_reason="stop",
            message=SimpleNamespace(content=insufficient_json()),
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    result = agent.generate_diagnosis(
        "Investigate checkout failures.",
        steps(),
        settings=settings,
    )

    assert result.status == "insufficient_evidence"


@pytest.mark.parametrize("content", [
    insufficient_json(),
    '{"status":',
])
def test_limit_termination_is_rejected_and_usage_preserved(monkeypatch, content):
    usage = UsageCollector()

    def fake_chat(**kwargs):
        return SimpleNamespace(
            done_reason="length",
            prompt_eval_count=100,
            eval_count=512,
            message=SimpleNamespace(content=content),
        )

    monkeypatch.setattr(agent, "chat", fake_chat)

    with pytest.raises(
        agent.DiagnosisGenerationLimitError,
        match="output-token limit",
    ):
        agent.generate_diagnosis(
            "Investigate checkout failures.",
            steps(),
            settings=DiagnosisSettings(num_predict=512),
            usage=usage,
        )

    totals = usage.snapshot()["totals"]
    assert totals["attempts"] == 1
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 512


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_generation_limit_requires_positive_integer(value):
    with pytest.raises(ValidationError):
        DiagnosisSettings(num_predict=value)


def test_evaluation_cli_forwards_generation_limit():
    from evals.runner import parse_arguments

    args = parse_arguments(["--num-predict", "512"])

    assert args.diagnosis_settings.num_predict == 512
    assert args.diagnosis_settings.ollama_options()["num_predict"] == 512


@pytest.mark.parametrize("value", ["0", "-1"])
def test_evaluation_cli_rejects_nonpositive_generation_limit(value):
    from evals.runner import parse_arguments

    with pytest.raises(SystemExit) as error:
        parse_arguments(["--num-predict", value])

    assert error.value.code == 2
