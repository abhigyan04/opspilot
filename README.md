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
Enter to decline. It then prints a separate `remediation` record and, after
simulated execution, a `verification` record. Output
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
successful version change alone does not demonstrate incident recovery.

## Simulated recovery verification

After simulated execution, the CLI loads separate post-action observations
from `data/scenarios/checkout_regression/recovery.json`. The loader requires
the execution's service and version transition to match the scenario. Declined
remediation does not load recovery data or produce a verification result.
The original investigation metrics remain unchanged, so the investigation
does not receive future recovery observations.

Python evaluates the error rate using a fixed demo policy:

- Consider only the requested service's measurements strictly after action
  completion and at or before the observation cutoff.
- Select the latest three distinct timestamps. Duplicate timestamps count
  once; conflicting duplicates retain the higher error rate.
- Report `recovered` if all three values are at or below 2%, `not_recovered`
  if three are available and any exceeds 2%, or `inconclusive` if fewer than
  three are available.

Measurements require timezone-aware timestamps and finite error rates between
0 and 1. The observation cutoff cannot precede action completion. Results
include `mode: simulation`, the threshold, required sample count, and evaluated
samples so the decision can be inspected.

The fixture scripts a rollback from `1.7.4` to `1.7.3` at 14:10 UTC on
28 September 2026, followed by observations through 14:13 UTC. These are
scenario timestamps, not wall-clock execution times or fresh production
measurements. The current fixture describes recovery; unit tests also cover
non-recovery and insufficient data. Three samples below the threshold verify
this demo policy, not overall service health or sustained recovery. No sample
cadence or maximum sample age within the supplied window is enforced yet.

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

Verification tests cover input validation, all three recovery outcomes,
time and service filtering, duplicate handling, scenario matching, skipping
observations after decline, and approved execution followed by verification.

## Evaluation runner

With Ollama running and `qwen3:4b` available, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m evals.runner
```

The runner currently evaluates the checkout regression scenario by performing
investigation and diagnosis. It does not request approval or execute remediation.
Evaluation code runs from the checkout; `evals` is not currently included in
the installed application package.

Each completed run saves a unique JSON report under `out/evals/`, which is
ignored by Git. Reports include a run ID, UTC start time, incident, full
investigation and diagnosis, stage durations, and these investigation metrics:

- `required_tool_coverage`: the fraction of scenario-required tool names used
  at least once. Repeated calls do not increase coverage; empty results still
  count as calls.
- `missing_tools`: required tool names that were not used.
- `tool_calls`: total executed tool calls.
- `stopped_by_model` and `hit_step_limit`: how investigation ended.

The reference root cause is stored for assessment and is not passed to the
investigation or diagnosis functions. Diagnosis accuracy remains explicitly
`not_scored`. Full tool coverage does not establish useful evidence, correct
arguments, a correct diagnosis, or overall task success.

Durations include local model processing and any model-loading overhead. A
first local run achieved full required-tool coverage with four calls and took
about 173 seconds; this is a single observation, not a performance benchmark.
Model outputs can vary between runs. Reports do not yet capture model versions,
generation settings, or repository revisions needed for stronger reproducibility.

Runner tests mock model-dependent functions and check reference-answer
separation, report contents, directory creation, and overwrite protection.
They run in normal CI; live evaluations remain a separate local command.
Exceptions currently abort a run before a report is saved, so unsuccessful
attempts are not yet represented in saved reports.

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
job before tests run; expand the failed step to read its logs. The first hosted
CI run passed on `master` for commit `31f816c` on 7 October 2026, completing in
17 seconds. CI currently runs tests only; it does not deploy OpsPilot or
execute the interactive remediation CLI.

On 7 October 2026, a failure-and-recovery exercise on `codex/ci-learning`
verified that an intentional assertion failure made CI fail with exit code 1
(1 failed, 56 passed). Removing the temporary test restored a successful
hosted run at commit `15bad7f`. The exercise also exposed a test-discovery
mistake: a file missing the `.py` extension was skipped, leaving a green run
with only the original 56 tests. A passing check covers collected tests, not
necessarily every intended test. The exercise was kept off `master`.

## Next milestone

Extend evaluation with failure reports and repeated-run summaries, then add
incident scenarios and diagnosis assessment for unsupported causal claims and
appropriate remediation. Keep deterministic software tests separate from live
model evaluations. Automated deployment of OpsPilot will follow once there is
a deployable service.
