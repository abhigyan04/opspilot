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

The diagnosis generation schema restricts citation strings to an enum of IDs
collected during that investigation. The prompt also lists the exact allowed
IDs. Python independently checks every root-cause and supporting-claim citation;
unknown IDs raise `ValueError` even if generation constraints are bypassed.
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
required for the test suite. Run commands from the repository root so Python
can discover the application, evaluation modules, and tests. Default fixture
paths are resolved relative to the source files, not the working directory.

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

## Scenario selection

Investigation tools accept an application-supplied, keyword-only `data_dir`.
The default checkout scenario is resolved relative to the source files rather
than the working directory. Each tool call reads from its selected directory
without changing shared global scenario state.

`investigate` passes that directory through `execute_tool` to logs, metrics,
deployments, and commit lookup. Each `EvaluationCase` requires an explicit
`scenario_dir`, which the evaluation runner supplies to investigation. Fixture
paths are not part of model-facing tool argument schemas.

Scenario directories contain `log.json`, `metrics.json`, `deployments.json`,
and `commits.json`. Tests check per-call isolation and that investigation and
the evaluation runner forward the chosen scenario. Remediation and recovery
in the interactive demo remain checkout-specific.

## Evaluation runner

With Ollama running and `qwen3:4b` available, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m evals.runner
.\.venv\Scripts\python.exe -m evals.runner --runs 2
.\.venv\Scripts\python.exe -m evals.runner --case payment_provider_outage --runs 1
```

The runner performs investigation and diagnosis for the selected registered
case. `--case` defaults to `checkout_regression`; `payment_provider_outage` is
also available. Unknown case names are rejected before a model run starts.
The runner does not request approval or execute remediation.
Evaluation code runs from the checkout; `evals` is not currently included in
the installed application package.

Both cases use the same incident prompt. The checkout regression requires
connecting a code change to an AttributeError. The payment-provider case has
PayBridge HTTP 503 responses and elevated error rates before a nearby
checkout deployment that adds logging only. The evidence does not support
blaming that deployment for the onset, or explain the provider's internal
failure. An available rollback target is not evidence that rollback is useful.

The default is one attempt; `--runs` selects a positive number of sequential
attempts. Each batch saves individual JSON reports and `summary.json` under
`out/evals/<batch-id>/`, which is ignored by Git. Each attempt is saved before
the next starts, and existing files are never overwritten. Version 2 reports
include a run ID, UTC start time, incident, available investigation and diagnosis,
stage durations, completion status, and these investigation metrics:

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

Exceptions during investigation, coverage scoring, or diagnosis produce a
`failed` report with the error stage, type, and message. Completed stages are
preserved; timings for stages never started remain null. An investigation
failure does not preserve its internal partial history because the agent does
not yet return it. Recorded failures allow the batch to continue. Interrupted
processes and report-writing failures still stop the batch; already saved
attempts remain available. The CLI exits with code 1 if any recorded attempt
failed, otherwise 0. `completed` means the pipeline finished, not that it
correctly diagnosed the incident.

Batch summaries accept version 2 reports for one case and include all attempts
in `pipeline_completion_rate` and mean total duration. Mean tool coverage uses
only reports with computed metrics, including diagnosis failures where metrics
exist; `coverage_observations` exposes this denominator. Missing coverage is
not treated as zero. Failure counts are grouped by stage, and diagnosis
accuracy remains null (unmeasured).

A two-attempt local batch completed both attempts with a mean duration of about
150 seconds and mean tool coverage of 87.5%. One attempt omitted `query_metrics`
and returned insufficient evidence; the other used all four required tools.
These small-sample observations illustrate run variability, not reliable
accuracy or latency estimates.

Initial payment-provider runs failed citation validation after the model invented
IDs, including timestamp-based labels and shortened IDs such as `evidence-1`.
After restricting the generation schema, a subsequent run completed in about
149 seconds with full tool coverage but returned `insufficient_evidence`.
It recognized provider errors preceding deployment, yet speculated without
evidence that the logging deployment was a response to the incident. This
branch contains no structured citations, so that completed run does not prove
the model can generate valid cited diagnoses under the new constraint. These
observations remain evaluation findings, not a measured diagnosis-accuracy score.

A subsequent diagnosis-prompt revision distinguishes an observed failure
mechanism from unknown deeper causes and forbids inferring deployment intent.
One fresh run per scenario completed with full tool coverage and `supported`
diagnoses, taking about 163 seconds for the provider case and 174 seconds for
the checkout regression. All citation IDs passed validation, but inspection
found incorrect or incomplete claim-to-evidence mappings: the provider root
cause cited metrics and deployment records instead of the HTTP 503 logs.
The checkout diagnosis also asserted unauthenticated requests without evidence
of authentication state, and the provider diagnosis described unavailability
as temporary without recovery observations. These runs demonstrate that valid
IDs do not establish citation relevance or well-calibrated claims. They do not
establish a reliable improvement from the prompt change; human reviews remain
separate records.

Runner and summary tests mock model-dependent functions and check reference-answer
separation, report contents, overwrite protection, failure recording, persistence
before subsequent attempts, summary denominators, invalid batch sizes, case
selection, and the outage fixture's pre-deployment failures. Mocked diagnosis
tests check the restricted citation schema and rejection of unknown IDs.
They run in normal CI; live evaluations remain a separate local command.

## Human diagnosis review

Review an individual version 2 run report from the repository root:

```powershell
python -m evals.review out/evals/<batch-id>/<run-id>.json --reviewer "Abhigyan"
```

Replace the placeholders with the actual report path, not `summary.json`.
The CLI displays the report, including collected observations, diagnosis, and
reference answer, then asks for a verdict and a nonblank rationale for each
criterion:

- `causal_explanation`: identifies the failure mechanism supported by evidence.
- `deployment_reasoning`: interprets deployment timing and changes correctly.
- `evidence_grounding`: supports factual claims and citations without invented
  explanations.
- `uncertainty_handling`: distinguishes known facts from unknowns and chooses
  whether to abstain appropriately.

Choose `1` for `met`, `2` for `not_met`, or `3` for `not_assessable`. Invalid
choices and blank rationales prompt again. An absent diagnosis requires
`not_assessable` for every criterion. An `insufficient_evidence` response is
still a diagnosis that can be reviewed; it does not automatically make every
criterion unassessable. Earlier model reasoning is not operational evidence.

After all four criteria are entered, the CLI saves `<run-id>.review.json`
beside the source report. It validates run and case IDs, records the reviewer,
rubric version and source-report SHA-256, and refuses to overwrite a review.
The source report remains unchanged. Cancelling during collection with Ctrl+C
or end-of-input saves no partial review.

The hash records the report bytes read at save time; it is not a signature or
reviewer authentication. Reviews remain local under the ignored `out/` directory.

Summarize saved reviews for a batch without running the model again:

```powershell
python -m evals.review_summary out/evals/<batch-id>
```

The command reads only the run reports listed in the batch's `summary.json`.
For each saved review, it verifies the source filename, SHA-256, run and case
IDs, and review schema. A missing review counts as unreviewed; an invalid review
raises an error instead of being silently skipped. Missing reports, duplicate
run IDs, mixed cases, and inconsistent batch case or attempt counts are rejected.

The printed JSON includes reviewed and unreviewed run counts. Each criterion
reports `met`, `not_met`, `not_assessable`, and `assessable` counts, with
`met_rate = met / (met + not_met)`. Unreviewed and unassessable results are
excluded from that denominator; the rate is null when none are assessable.
The command leaves the automated batch summary and source reports unchanged,
including their original unscored diagnosis assessment.

The first reviewed payment-provider run met causal explanation and deployment
reasoning, but did not meet evidence grounding or uncertainty handling. These
are one reviewer's judgments for one run, not a measured model-accuracy rate.
Tests cover review integrity checks, aggregation denominators, and loading
only the reports listed in the batch manifest. They require no Ollama server.

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

Use the review findings to improve diagnosis grounding and uncertainty handling,
then compare fresh evaluations across both scenarios using the same rubric.
Remediation appropriateness also needs evaluation before extending the checkout
demo to other cases. Keep deterministic software tests separate from live
model evaluations. Automated deployment of OpsPilot will follow once there is
a deployable service.
