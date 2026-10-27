import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError

from app import main as api
from app.agent import agent
from app.agent.settings import RuntimeSettings
from app.agent.schemas import diagnosis_adapter
from app.agent.workflow import build_investigation_graph
from app.agent.workflow_cli import start_workflow, resume_workflow


@pytest.fixture(autouse=True)
def clean_runtime_env(monkeypatch):
    for name in RuntimeSettings.model_fields:
        monkeypatch.delenv(f"OPSPILOT_{name.upper()}", raising=False)


def test_defaults_and_environment_are_resolved_without_import_cache(monkeypatch):
    assert RuntimeSettings.from_env() == RuntimeSettings()
    monkeypatch.setenv("OPSPILOT_INVESTIGATION_MODEL", " custom:small ")
    monkeypatch.setenv("OPSPILOT_MAX_STEPS", "2")
    settings = RuntimeSettings.from_env()
    assert settings.investigation_model == "custom:small"
    assert settings.max_steps == 2
    monkeypatch.setenv("OPSPILOT_INVESTIGATION_MODEL", "custom:large")
    assert RuntimeSettings.from_env().investigation_model == "custom:large"
    assert settings.investigation_model == "custom:small"


@pytest.mark.parametrize("name,value", [
    ("INVESTIGATION_MODEL", " "), ("DIAGNOSIS_MODEL", ""),
    ("WORKFLOW_DIAGNOSIS_MODEL", "\t"), ("SERVICE", " "),
    ("MAX_STEPS", "0"), ("MAX_STEPS", "invalid"),
    ("WORKFLOW_NUM_CTX", "-1"), ("WORKFLOW_NUM_PREDICT", "0"),
])
def test_invalid_environment_fails_validation(monkeypatch, name, value):
    monkeypatch.setenv(f"OPSPILOT_{name}", value)
    with pytest.raises(ValidationError):
        RuntimeSettings.from_env()


def test_choose_tool_uses_environment_and_explicit_model_wins(monkeypatch):
    models = []
    def fake_chat(**kwargs):
        models.append(kwargs["model"])
        return SimpleNamespace(message=SimpleNamespace(
            content='{"tool":"finish","reason":"Done."}'
        ))
    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setenv("OPSPILOT_INVESTIGATION_MODEL", "custom:small")
    agent.choose_next_tool([])
    agent.choose_next_tool([], model="explicit:model")
    assert models == ["custom:small", "explicit:model"]


def test_api_captures_runtime_settings_at_startup(tmp_path, monkeypatch):
    calls = []
    async def fake_start(**kwargs):
        calls.append(kwargs)
        return {"thread_id": kwargs["thread_id"], "next": [], "state": {}, "interrupts": []}
    monkeypatch.setattr(api, "start_workflow", fake_start)
    monkeypatch.setenv("OPSPILOT_WORKFLOW_DIAGNOSIS_MODEL", "custom:diagnosis")
    monkeypatch.setenv("OPSPILOT_SERVICE", "inventory-service")
    app = api.create_app(database=tmp_path / "checkpoints.sqlite")
    monkeypatch.setenv("OPSPILOT_SERVICE", "changed-service")
    with TestClient(app) as client:
        assert client.post("/workflows", json={"incident": "Investigate inventory."}).status_code == 201
    assert calls[0]["model"] == "custom:diagnosis"
    assert calls[0]["runtime_settings"].service == "inventory-service"


def test_standalone_diagnosis_and_evaluation_use_environment(monkeypatch):
    from evals.runner import parse_arguments

    monkeypatch.setenv("OPSPILOT_DIAGNOSIS_MODEL", "custom:diagnosis")
    assert parse_arguments([]).model == "custom:diagnosis"
    models = []
    def fake_chat(**kwargs):
        models.append(kwargs["model"])
        return SimpleNamespace(message=SimpleNamespace(content=(
            '{"status":"insufficient_evidence","reason":"No logs.",'
            '"missing_evidence":["Logs"]}'
        )))
    monkeypatch.setattr(agent, "chat", fake_chat)
    steps = [{"evidence_id": "evidence-001", "decision": {
        "tool": "search_logs", "arguments": {"service": "checkout-service", "level": "ERROR"},
    }, "result": []}]
    agent.generate_diagnosis("Investigate.", steps)
    agent.generate_diagnosis("Investigate.", steps, model="explicit:diagnosis")
    assert models == ["custom:diagnosis", "explicit:diagnosis"]


@pytest.mark.parametrize("legacy", [False, True])
def test_restart_keeps_saved_models_service_and_limits(tmp_path, monkeypatch, legacy):
    database = tmp_path / "workflow.sqlite"
    calls = []
    async def fail_investigation(*args, **kwargs):
        raise ConnectionError("planned failure")
    monkeypatch.setattr(agent, "investigate_async", fail_investigation)
    initial_model = "qwen3:4b" if legacy else "custom:investigation"
    settings = RuntimeSettings(
        investigation_model=initial_model, service="inventory-service",
        max_steps=2, workflow_num_ctx=6144, workflow_num_predict=1024,
    )

    async def check():
        with pytest.raises(ConnectionError):
            await start_workflow(
                database=database, thread_id="test", incident="Investigate inventory.",
                scenario="checkout_regression", model="explicit:diagnosis",
                runtime_settings=settings,
            )
        if legacy:
            async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
                graph = build_investigation_graph(checkpointer=saver)
                config = {"configurable": {"thread_id": "test"}}
                snapshot = await graph.aget_state(config)
                old = dict(snapshot.values["workflow_config"])
                old["version"] = 4
                old.pop("investigation_model")
                # Preserve the failed task while emulating an existing v4 checkpoint.
                checkpoint = await saver.aget_tuple(config)
                checkpoint.checkpoint["channel_values"]["workflow_config"] = old
                await saver.aput(checkpoint.config, checkpoint.checkpoint,
                                 checkpoint.metadata, {})

        monkeypatch.setenv("OPSPILOT_INVESTIGATION_MODEL", "changed:investigation")
        monkeypatch.setenv("OPSPILOT_WORKFLOW_DIAGNOSIS_MODEL", "changed:diagnosis")
        monkeypatch.setenv("OPSPILOT_SERVICE", "changed-service")
        monkeypatch.setenv("OPSPILOT_MAX_STEPS", "5")
        async def investigate(*args, **kwargs):
            calls.append(kwargs)
            return {"status": "finished", "reason": "No observations.", "steps": []}
        def diagnose(*args, **kwargs):
            assert kwargs["model"] == "explicit:diagnosis"
            assert kwargs["settings"].num_ctx == 6144
            assert kwargs["settings"].num_predict == 1024
            return diagnosis_adapter.validate_python({
                "status": "insufficient_evidence", "reason": "No observations.",
                "missing_evidence": ["Logs"],
            })
        monkeypatch.setattr(agent, "investigate_async", investigate)
        monkeypatch.setattr(agent, "generate_diagnosis", diagnose)
        result = await resume_workflow(database=database, thread_id="test", retry=True)
        assert result["state"]["workflow_config"]["service"] == "inventory-service"
    asyncio.run(check())
    assert calls[0]["model"] == initial_model
    assert calls[0]["max_steps"] == 2
