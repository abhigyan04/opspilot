# OpsPilot

An evaluation-driven incident investigation agent for the fictional Acme
Commerce platform. The current milestone selects one operational tool with
model-generated, validated arguments and executes it against synthetic data.

## Run locally

From the repository root, using Python 3.10 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
ollama pull qwen3:4b
.\.venv\Scripts\python.exe -m app.agent.agent
```

Ollama must be running locally. The example incident explicitly identifies
`checkout-service`; the agent prints its selected tool, arguments, reason, and
returned evidence.

Each tool has a Pydantic argument schema, selected through the `tool`
discriminator. Invalid tool names, missing required fields, invalid log levels,
and extra fields are rejected before dispatch. `query_metrics` takes
`metric_name`; `search_logs` requires both `service` and `level`.

The prompt tells the model to use only available information. Schema validation
checks argument structure, but does not prove that values are supported by
evidence. The current agent performs one tool call, without diagnosis or
remediation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use synthetic fixtures and mocked model responses, so Ollama is not
required for the test suite. Run commands from the repository root because the
tools currently resolve fixture paths relative to the working directory.

The next milestone is a bounded investigation loop that feeds tool results
back to the model so it can use newly discovered information in later calls.
