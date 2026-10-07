# OpsPilot

An evaluation-driven incident investigation agent for the fictional Acme
Commerce platform. The agent investigates synthetic incidents through a bounded
loop, selecting operational tools with model-generated, validated arguments
and feeding their results back into subsequent decisions. It then generates a
structured diagnosis and validates its evidence references. A human can review
and approve a rollback candidate for in-memory simulation.

## Run locally

From the repository root, using Python 3.10 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
ollama pull qwen3:4b
.\.venv\Scripts\python.exe -m app.agent.agent
```

Ollama must be running locally. The example incident explicitly identifies
`checkout-service`; the agent prints JSON containing `investigation` and
`diagnosis` records. If a rollback candidate is available, the CLI displays
its proposal ID and contents, then prompts for approval. Enter
`approve <proposal-id>` using the displayed ID to simulate execution, or press
Enter to decline. It then prints a separate `remediation` record. Output
includes interactive text and multiple JSON records, not a single JSON document.

## Investigation loop

Each iteration passes the incident and conversation history to Qwen3. The
model selects a tool or chooses `finish`. Tool decisions are validated before
execution, and their results are appended to the history so later decisions
can use discovered information, such as a deployment's commit hash.

`investigate(incident, max_steps=6)` allows up to six model decisions by
default. A `finish` decision counts toward this limit and does not execute a
tool. The `investigation` record contains:

- `status`: `finished` when the model chooses to stop, or `step_limit` when
  the decision limit is exhausted.
- `reason`: the model's stopping explanation or the step-limit message.
- `steps`: the execution history, with each tool's decision (name, arguments,
  and reason), returned result, and Python-generated `evidence_id`.

Evidence IDs identify entire tool responses, including empty responses, and
are local to each investigation. The model receives these same IDs alongside
the observations in its conversation history.

Each tool has a Pydantic argument schema, selected through the `tool`
discriminator. Invalid tool names, missing required fields, invalid log levels,
and extra fields are rejected before dispatch. `query_metrics` takes
`service` and `metric_name`, currently restricted to `error_rate`;
`search_logs` requires both `service` and `level`.

The prompt tells the model to use only available information. Schema validation
checks argument structure, but does not prove that values are supported by
evidence. A `finished` status records the model's choice to stop; it does not
certify a diagnosis. The model may still overstate conclusions in its stopping
reason.

## Structured diagnosis

After investigation, a separate model call assesses the collected tool
observations. It receives the incident, evidence IDs, tool names, arguments,
and results, without the investigation model's earlier reasoning or stopping
explanation.

The diagnosis returns either:

- `supported`: a proposed root cause, supporting claims with evidence
  citations, and limitations.
- `insufficient_evidence`: a reason and a list of missing evidence.

Python checks every root-cause and supporting-claim citation against IDs
collected during that investigation. Unknown IDs raise `ValueError`.
With no collected steps, diagnosis returns insufficient evidence without
calling the model.

Diagnosis also runs after the investigation reaches its step limit. The
default run permits six investigation decisions plus one diagnosis call.

Citation validation checks that references exist; it does not prove that
the evidence supports the claim. The `supported` status is the model's
assessment. A live run incorrectly described the refactor as causing
`request.user` to become `None`, rather than introducing an access that fails
when it is already `None`. Diagnosis accuracy remains an evaluation concern.

## Human-approved simulated remediation

A supported diagnosis and exactly one collected deployment record for the
requested service can produce a rollback candidate. The target comes from the
fixture's explicit `rollback_target_version`; it is not inferred from version
numbers. Missing targets, ambiguous records, or insufficient diagnoses produce
no candidate. This rule does not establish that rollback is the appropriate
remedy; the human must assess the diagnosis and its limitations.

Before submission, Python validates the service, current version, available
target, and evidence references. A session stores a JSON snapshot of the proposal
under a generated ID. Editing the original object does not change that snapshot.
Approval is granted through the CLI, outside the model's available tools.

Only the approval phrase containing the displayed proposal ID authorizes
execution (surrounding whitespace is ignored). Other answers, end-of-input,
or Ctrl+C at the approval prompt decline the proposal. Execution rechecks the
supplied simulation state, requires approval, and prevents repeat execution
of the same proposal. It consumes approval and reports `status: simulated`;
declining reports `status: declined`.

The CLI initializes simulation state from the deployment fixture before review.
Execution changes only this in-memory version and clears its rollback target.
It does not alter fixtures, call deployment infrastructure, or re-read external
state at execution time. Sessions are not persisted or authenticated, and a
successful simulation does not demonstrate incident recovery.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use synthetic fixtures and mocked model responses, so Ollama is not
required for the test suite. Run commands from the repository root because the
tools currently resolve fixture paths relative to the working directory.

Tests cover argument validation and dispatch, passing tool evidence to the next
decision, finishing without executing a tool, and enforcing the step limit.
They also cover diagnosis schemas, acceptance of collected evidence IDs,
rejection of unknown citations, the observations sent to diagnosis generation,
and the no-evidence fallback without a model call. These deterministic tests
verify orchestration and citation integrity, not model diagnosis accuracy.

Remediation tests cover target and evidence validation, proposal snapshot
isolation, explicit approval, rejection of changed simulation state, prevention
of repeat execution, proposal eligibility, and CLI approval versus decline.

## Continuous integration

The workflow in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) is
configured to run on pushes and pull requests. Its `Python tests` job uses
Ubuntu and Python 3.12, checks out the repository, installs the project with
its development dependencies using `python -m pip install -e ".[dev]"`, and
runs `python -m pytest -q`. The job has read-only repository permissions and
a ten-minute timeout.

The suite uses mocked model responses, so CI needs no Ollama server, model
download, GPU, or API key. This workflow tests one Python version; it does not
yet verify every version allowed by the project's Python requirement.

After pushing the workflow, open the repository's **Actions** tab, select
**CI**, and inspect the **Python tests** job. A failed installation stops the
job before tests run; expand the failed step to read its logs. A successful
hosted run is still pending initial verification. CI currently runs tests
only; it does not deploy OpsPilot or execute the interactive remediation CLI.

## Next milestone

Verify the first hosted CI run and practice diagnosing a failed check on a
branch. Then extend the incident simulation with post-remediation recovery
verification. Keep diagnosis accuracy and unsupported causal claims visible
as evaluation concerns. Automated deployment of OpsPilot will follow once
there is a deployable service.
