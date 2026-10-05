# OpsPilot

An evaluation-driven incident investigation agent for the fictional Acme
Commerce platform. The agent investigates synthetic incidents through a bounded
loop, selecting operational tools with model-generated, validated arguments
and feeding their results back into subsequent decisions.

## Run locally

From the repository root, using Python 3.10 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
ollama pull qwen3:4b
.\.venv\Scripts\python.exe -m app.agent.agent
```

Ollama must be running locally. The example incident explicitly identifies
`checkout-service`; the agent prints a JSON investigation record.

## Investigation loop

Each iteration passes the incident and conversation history to Qwen3. The
model selects a tool or chooses `finish`. Tool decisions are validated before
execution, and their results are appended to the history so later decisions
can use discovered information, such as a deployment's commit hash.

`investigate(incident, max_steps=6)` allows up to six model decisions by
default. A `finish` decision counts toward this limit and does not execute a
tool. The returned JSON contains:

- `status`: `finished` when the model chooses to stop, or `step_limit` when
  the decision limit is exhausted.
- `reason`: the model's stopping explanation or the step-limit message.
- `steps`: the execution history, with each tool's decision (name, arguments,
  and reason) and returned result.

Each tool has a Pydantic argument schema, selected through the `tool`
discriminator. Invalid tool names, missing required fields, invalid log levels,
and extra fields are rejected before dispatch. `query_metrics` takes
`service` and `metric_name`, currently restricted to `error_rate`;
`search_logs` requires both `service` and `level`.

The prompt tells the model to use only available information. Schema validation
checks argument structure, but does not prove that values are supported by
evidence. A `finished` status records the model's choice to stop; it does not
certify a diagnosis. The model may still overstate conclusions in its stopping
reason. Structured, evidence-backed diagnosis is not implemented yet, and the
agent does not perform remediation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use synthetic fixtures and mocked model responses, so Ollama is not
required for the test suite. Run commands from the repository root because the
tools currently resolve fixture paths relative to the working directory.

Tests cover argument validation and dispatch, passing tool evidence to the next
decision, finishing without executing a tool, and enforcing the step limit.

## Next milestone

Add structured, evidence-backed diagnosis: assign IDs to returned evidence,
require conclusions to cite those IDs, and reject references to evidence the
agent never received. Valid references alone will not prove that a conclusion
is supported; assessing that remains part of evaluation.
