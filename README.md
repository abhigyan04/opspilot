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
requested service can produce a rollback candidate only when the root-cause
claim cites that deployment and a matching `get_commit` observation. The
deployment's commit hash must match both the requested commit hash and the
returned hash, and the result must contain a nonblank code diff. Citations in
supporting claims alone do not satisfy this requirement.

The target comes from the fixture's explicit `rollback_target_version`; it is
not inferred from version numbers. Missing targets, ambiguous records,
insufficient diagnoses, or missing required root-cause citations produce no
candidate. These checks establish citation linkage and available change data,
not that the change caused the failure or rollback is appropriate. The human
must still assess the diagnosis and its limitations before approval.

A conservative timeline guard also suppresses the candidate if an identical,
nonblank error message appears for the requested service on the rollback
target version strictly before deployment and on the current version strictly
after it. It examines all collected `search_logs` results, including uncited
observations, and accepts `ERROR` or `CRITICAL` records. Timestamps must be
parseable and timezone-aware; comparisons use their actual instants.

This guard uses exact message equality, not semantic error classification.
Missing or invalid timestamps and absent version labels cannot establish the
required pair. A record exactly at deployment time establishes neither side.
No matching pair means only that this blocker did not apply, not that rollback
is justified. Conversely, recurring background errors can suppress a candidate
even if a deployment worsened a separate failure; this is a conservative demo
policy, not a general proof of rollback ineffectiveness.

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

### Remediation proposal evaluation

`evals/remediation.py` evaluates a proposal against fixture-specific expectations
that are kept separate from agent inputs. Checkout regression expects a
`rollback_service` candidate for `checkout-service` from `1.7.4` to `1.7.3`;
the provider outage and sparse-evidence scenarios expect no rollback candidate.
Unknown cases raise an error. Matching checks action, service, current version,
and target version, or the absence of a proposal. It does not score the reason,
citations, approval process, execution, or recovery.

On 13 October 2026, the original proposal policy was evaluated against all nine
saved diagnoses from comparison `ee0df895-d512-45d1-8501-e888b4702f6d`:

| Scenario | Attempts | Action-and-target matches |
| --- | --- | --- |
| Checkout regression | 3 | 3 |
| Payment provider outage | 3 | 1 |
| Sparse evidence | 3 | 3 |

The 7/9 matches are a proposal baseline, not overall remediation accuracy.
Provider seeds 42 and 43 produced checkout rollback candidates despite
diagnosing PayBridge failures. Seed 44 produced no candidate because its
diagnosis abstained; that match does not show that the proposal policy
recognized the external failure. Likewise, matching checkout targets does
not establish that their diagnosis explanations were fully grounded.

The local baseline is saved at
`out/remediation/73f588cf-8b08-44a8-b33d-13b38c074ab4.json`, outside Git. It records
each input report's path, run ID, SHA-256, model, seed, diagnosis status, full
proposal, and assessment, plus hashes of the proposal-builder and evaluator
source files. Both code hashes and all nine report hashes were verified, and
the proposals and aggregate counts were reproduced from those inputs.
This initial baseline used a local script, without another model call, approval
request, or rollback execution. The CLI below now supports this workflow.

The baseline's user-reported test run passed all 197 tests, including scenario
expectations, wrong services and versions, missing proposals, and unknown cases.

After adding the root-cause citation requirement, a comparison against the same
nine reports produced 9/9 action-and-target matches. Only provider seeds 42 and
43 changed: their checkout rollback candidates became null because their root
causes cite provider logs rather than the deployment and matching code change.
All checkout candidates and sparse-evidence abstentions were unchanged.

The comparison is saved locally at
`out/remediation/edcbc78b-7c2d-46bf-8bb3-5ff02775117c.json`. The baseline hash,
unchanged evaluator hash, revised policy hash, all nine source hashes, and
reproduced proposals and assessments were verified. The user reported 206
passing tests, including missing citations, unrelated commits, unavailable
diffs, missing deployment commit hashes, and provider-log-only diagnoses.

This improvement is specific to the saved proposals. An incorrect root cause
that cites both the deployment and matching commit can still pass this check.
No semantic causal validation, approval, execution, or recovery was evaluated
by the 9/9 result; the existing approval and execution checks remain separate.

The timeline guard was subsequently added after a regression test showed that
adding deployment and commit citations could bypass the citation-only rule.
The user reported 222 passing tests, including the contradictory timeline,
different messages, services and versions, strict time boundaries, timezone
offsets, unusable log timestamps, and uncited contradictory logs.

Rechecking the same nine source reports with the timeline guard preserved all
nine proposals and assessments from the saved comparison above: 9/9 matches.
Source hashes and the unchanged evaluator hash were verified. Additional
in-memory probes added all observation IDs to the root-cause citations of
provider seeds 42 and 43; both still produced no candidate, with the timeline
guard recognizing the matching pre- and post-deployment failures. No model,
approval, or execution step ran, and saved reports were not changed. The saved
comparison retains the earlier citation-only policy hash; this later recheck
did not overwrite it.

### Offline remediation evaluation CLI

Evaluate the current proposal policy against one saved report or all diagnosis
replays in a comparison directory, without generating new diagnoses:

```powershell
python -m evals.remediation_runner out/evals/11924a4b-1f35-4593-b085-b40d52a97c4f/c84105a0-581a-48af-9bbb-b495227adf84.json --service checkout-service
python -m evals.remediation_runner out/comparisons/ee0df895-d512-45d1-8501-e888b4702f6d --service checkout-service
```

`--service` is required. `--output-dir` defaults to `out/remediation`; when the
input is a directory, the output must be outside that directory. A single input
can be a completed version-2 full-pipeline or diagnosis-replay report with a
diagnosis. Directory discovery recursively selects diagnosis replay reports,
skipping `summary.json` and review sidecars. Unsupported cases, invalid sources,
and duplicate run IDs stop evaluation before an aggregate is saved.

The command saves a new version-1 `remediation_proposal_evaluation` report with
per-case counts and each source's absolute path, run ID, SHA-256, model,
settings, diagnosis status, generated proposal, and expected action and target.
It also records hashes of the proposal policy, evaluator, and runner files;
these three hashes are not a complete environment snapshot. Source reports
remain unchanged. No model call, approval request, or rollback execution runs.
Exit code 0 means the evaluation was saved, even if some proposals do not match.

On 13 October 2026, the CLI produced 9/9 action-and-target matches across the
same three scenarios, with three matches per scenario. The saved report is
`out/remediation/1e6f3ef2-3d61-4123-928e-4c4b4ea2b898.json`, outside Git. All nine
source identities and hashes, reproduced proposals and assessments, aggregate
counts, and all three current code hashes were verified. The full test suite
passed: 234 tests. This confirms the offline evaluation checkpoint, not overall
diagnosis accuracy or successful remediation.

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
.\.venv\Scripts\python.exe -m evals.runner --case sparse_evidence --runs 1
```

The runner performs investigation and diagnosis for the selected registered
case. `--case` defaults to `checkout_regression`; `payment_provider_outage` and
`sparse_evidence` are also available. Unknown case names are rejected before a
model run starts.
The runner does not request approval or execute remediation.
Evaluation code runs from the checkout; `evals` is not currently included in
the installed application package.

Use `--model` to select the diagnosis model (default `qwen3:4b`). The runner
also accepts `--num-ctx`, `--temperature`, `--top-p`, `--top-k`, `--seed`, and
`--think` / `--no-think`, with the same defaults as diagnosis replay:
4096, 0.6, 0.95, 20, 42, and thinking enabled. These options affect diagnosis
only; investigation continues to use its existing `qwen3:4b` configuration.
Both models must be available locally when different tags are selected.

```powershell
python -m evals.runner --case payment_provider_outage --runs 1 --model qwen3:8b --seed 42 --num-ctx 4096 --think
```

Every attempt receives the selected configuration. Individual reports record
`evaluation_mode: full_pipeline`, `diagnosis_model`, and `diagnosis_settings`,
including failed attempts. The CLI prints the batch summary; inspect its listed
individual reports for configuration and diagnosis details. Blank model tags
and invalid settings exit with code 2 before starting a batch. Model tags are
passed to Ollama; the CLI does not check whether a model is installed.

On 13 October 2026, batch `e50549e7-2c44-4a8a-a3ba-6b4befc78df9` completed a
fresh provider-outage investigation and diagnosis in 205.23 seconds with four
tool calls and full required-tool coverage. Its report
`88405562-a606-4f8a-b802-2c3257f6a562.json` recorded `qwen3:8b`, seed 42,
4096 context, and thinking enabled. Investigation took 148.37 seconds and
diagnosis took 56.86 seconds. The diagnosis returned `insufficient_evidence`,
recognizing unchanged provider errors across versions but failing to identify
the observed PayBridge failure mechanism as the supported explanation. The
evidence already shows failures before deployment. This run verifies settings
integration, not improved diagnosis accuracy; formal assessment remains
`not_scored`. The user reported 247 passing tests for the completed integration.

On 15 October 2026, diagnostic checks found that replay
`3156b1d3-f73e-4c83-961a-782d6338f756` started at 00:37:53 IST, about eight
seconds before the edited diagnosis prompt was saved. Its server log showed
1,204 input tokens, matching a probe of the previous committed prompt. The
saved edited prompt used 1,304 tokens. That replay therefore does not establish
that the edited prompt failed to improve the diagnosis.

A fresh diagnostic call using the saved edit, the same provider observations,
8B model, and seed-42 settings returned `supported` and identified PayBridge's
503 responses as the failure mechanism. It still overstated the exact start
time and gave an unclear deployment conclusion, so this is a partial improvement
on one input, not a validated quality improvement across scenarios. The test
suite passed all 247 tests. No additional review sidecar was saved. Request
provenance remains a gap: reports do not yet hash the exact prompt and schema
sent to the model, making edits during a run difficult to audit.

The user's saved replay `out/replays/e39f0e53-a8ae-4387-829f-59a5100e7136.json`
also returned `supported`, identifying PayBridge's 503 responses with the
matching log citation. Its source hash, copied investigation, model, and
settings were verified against the original full-pipeline report. However,
it incorrectly claimed that the error-rate spike coincided with deployment:
the rate was already 0.30 at 13:54, before the 13:57 deployment. This records
improved mechanism identification while deployment reasoning and evidence
grounding remain faulty. No formal review sidecar was created for this replay.

Diagnosis input now includes a chronological view of timestamped observation
records alongside the original observations. `app/agent/evidence.py` sorts
timezone-aware timestamps by instant and retains the original evidence IDs.
Records without usable timestamps are omitted from the timeline but remain in
the original observations. The timeline copies data; it does not infer failure
onset, classify metric values, or establish causation. Tests cover timezone
ordering, source preservation, unusable timestamps, and delivery to diagnosis.
The full suite passed 250 tests after this integration.

Three local 8B replays on 15 October 2026 used seed 42, context 4096,
temperature 0.6, top-p 0.95, top-k 20, and thinking enabled:

| Case | Replay ID | Observed diagnosis |
| --- | --- | --- |
| Payment provider outage | `2180a07b-adb4-4bed-804b-53b882afaa1b` | Supported PayBridge failure mechanism; removed the earlier false deployment-coincidence claim, but omitted explicit pre-deployment reasoning and overstated exclusion of checkout code changes. |
| Checkout regression | `32fe8f7f-699a-43bc-9c9a-994f999af86a` | Supported customer-lookup regression with relevant citations; wording about the absence of a guard and definitive deployment causation exceeds what the small diff and log alone establish. |
| Sparse evidence | `6eb3b985-444c-4f89-97ad-3d581ec9027a` | Appropriately abstained and described unavailable records without inventing a cause. Requested dependency-error evidence is one possible investigation direction, not a known requirement. |

Reports are saved under `out/replays/`, outside Git. Source hashes and copied
investigations were verified against their original reports. All three status
choices match scenario expectations, but these single attempts do not establish
diagnosis accuracy or reliable improvement across seeds. No new formal review
sidecars were created. Provider timeline reasoning and claim precision remain
the next diagnosis-quality targets.

Diagnosis input also now includes `deployment_timing`: calculated comparisons
between each timestamped deployment and the earliest returned ERROR or CRITICAL
log for the same service. Comparisons retain the original records and evidence
IDs. They establish ordering only; the model must assess whether the selected
error is relevant, and the earliest returned error is not necessarily incident
onset. Missing usable pairs produce an empty list.

Provider replay `ca1466fe-e267-4506-a3a5-e289a3263af8`, using the same source and
8B seed-42 settings, retained the supported PayBridge mechanism and explicitly
recognized that observed errors preceded deployment. Source integrity and copied
observations were verified. This is progress on the targeted timeline error,
but the temporal supporting claim cites deployment and commit observations
without citing the metric or log needed to establish the error time. It also
overstates the exclusion of checkout code and the precision of spike onset.
The suite passed 256 tests.

Follow-up replay checks produced mixed results:

| Case and seed | Replay ID | Finding |
| --- | --- | --- |
| Provider, 43 | `a0cd9d10-35ea-405d-a40f-5471511930d0` | Correctly cited both logs and deployment for the pre-deployment error; a limitation reintroduced misleading coincidence wording, and unchanged messages were used to overstate an unchanged mechanism. |
| Checkout, 42 | `fc5d6415-1c1b-482e-b81e-022067209bf4` | Retained the supported customer-lookup mechanism, but introduced a wrong seven-minute metric claim and omitted deployment evidence from that claim's citations. |
| Sparse evidence, 42 | `6d7fd021-c3d0-4035-918e-6005229581c0` | Retained appropriate abstention and described the lack of available causal evidence without inventing a mechanism. |

The checkout samples show 0.01 at 13:55 and 0.40 at 14:05, with deployment at
13:57: ten minutes separate those samples, and the 0.40 sample is eight minutes
after deployment. The new diagnosis instead claimed the increase happened
within seven minutes after deployment. Source hashes, copied investigations,
and requested configurations were checked for these replays. Expected status
choices were preserved, but claim-level grounding did not improve consistently.
These checks justify retaining the timing comparison as an evaluated feature,
not claiming a general diagnosis-accuracy gain. No new formal review sidecars
were saved; incorrect quantitative claims and incomplete citations remain open.

All three cases use the same incident prompt. The checkout regression requires
connecting a code change to an AttributeError. The payment-provider case has
PayBridge HTTP 503 responses and elevated error rates before a nearby
checkout deployment that adds logging only. The evidence does not support
blaming that deployment for the onset, or explain the provider's internal
failure. An available rollback target is not evidence that rollback is useful.

The sparse-evidence case has an error-rate increase but empty log, deployment,
and commit fixtures. The expected diagnosis is `insufficient_evidence`: the
metrics establish a problem without identifying its mechanism. Empty tool
results establish only that no matching records were returned, not that no
errors or deployments occurred. Required coverage includes metrics, logs, and
deployments; commit lookup is excluded because no commit hash is available.

Its first live run completed in about 159 seconds with three tool calls, full
required coverage, and an `insufficient_evidence` diagnosis. It did not invent
a commit hash or specific cause. However, investigation reasoning and diagnosis
both interpreted empty results as absence of deployments or error logs. The
diagnosis also attributed a time window to tools that currently filter only by
service and, for logs, level. The abstention decision was appropriate, but its
explanation overstated the evidence. This single observation does not establish
reliable abstention behavior. Fixture and CLI tests verify scenario contents
and selection without calling the model.

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
Model outputs can vary between runs. New reports capture the requested diagnosis
model tag and settings, but not immutable model digests, investigation generation
settings, or repository revisions needed for stronger reproducibility.

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

## Diagnosis replay

Rerun diagnosis against a saved investigation with the current diagnosis code
and prompt, without selecting or executing investigation tools again:

```powershell
python -m evals.replay out/evals/<batch-id>/<run-id>.json
python -m evals.replay out/evals/<batch-id>/<run-id>.json --model qwen3:8b
```

Replay defaults to `qwen3:4b`. Use `--model` to select another locally available
Ollama model and download it first, for example with `ollama pull qwen3:8b`.
New replay reports and CLI output record the requested tag in `diagnosis_model`,
including failed diagnosis attempts. Older reports lack this field. The tag
does not identify an immutable model digest or record resolved generation
settings. Investigation and the full evaluation runner still default to 4B;
selecting a replay model changes only diagnosis generation. Tests check default
and explicit model selection, citation validation, and model-tag persistence.

Replay now sends explicit generation settings and records them in
`diagnosis_settings` in both the saved report and CLI output, including failed
diagnosis attempts. Defaults and overrides are:

| CLI flag | Default | Purpose |
| --- | --- | --- |
| `--num-ctx` | `4096` | Requested context size |
| `--temperature` | `0.6` | Sampling temperature |
| `--top-p` | `0.95` | Sampling probability threshold |
| `--top-k` | `20` | Sampling candidate limit |
| `--seed` | `42` | Sampling seed |
| `--think` / `--no-think` | Enabled | Thinking mode |

For example:

```powershell
python -m evals.replay out/evals/<batch-id>/<run-id>.json --model qwen3:8b --seed 42 --num-ctx 4096 --think
```

The validated, immutable settings object sends `think` as a separate chat
argument and the remaining fields as Ollama options. Invalid CLI settings exit
with code 2 before loading a report or starting diagnosis. Tests verify default
and custom settings reach diagnosis generation, are saved and printed, and
remain recorded on failure. Direct diagnosis callers that omit settings retain
their previous behavior. The full evaluation runner now exposes the same
diagnosis overrides and records them in each attempt's report.

These are requested settings, not a complete snapshot of resolved server
defaults. Older reports without `diagnosis_settings` should not be assumed to
use this configuration. A fixed seed does not guarantee identical results
across model versions, runtimes, or hardware; prompt and model digests are not
yet recorded.

The source must be a version 2 report with an investigation that finished or
reached its step limit, a steps list, and a nonblank incident. A report whose
diagnosis failed can still be replayed. Only the incident and saved steps are
passed to diagnosis generation; the previous diagnosis, reference answer, and
human reviews are not model inputs. Generation projects the steps into tool
observations, excluding earlier model reasoning.

Each replay saves a separate version 2 report under `out/replays/` by default;
`--output-dir` selects another directory. The report has a new run ID,
`evaluation_mode: diagnosis_replay`, and source filename, run ID, and SHA-256
provenance. It retains the source investigation and any reference answer for
review. Source reports are unchanged, and existing output files are never
overwritten. Diagnosis exceptions produce a saved failure report and exit
code 1; source-loading and save errors also return 1. Successful execution
returns 0, which does not certify diagnosis quality.

Investigation and scoring durations, and coverage metrics, are null because
those stages were not rerun. Total duration covers loading the source and
diagnosis execution, excluding saving the report. Automated pipeline summaries
reject replay reports to avoid mixing diagnosis-only timings and completion
with full runs. Replays produce individual reports, without a batch manifest.
They can be reviewed using `python -m evals.review out/replays/<run-id>.json
--reviewer "Abhigyan"` on one line.

A first provider-case replay took about 86 seconds and returned
`insufficient_evidence`, whereas its source diagnosis was `supported`.
Inspection found that it misidentified the commit observation as error logs,
called the provider unavailability temporary without recovery evidence, and
claimed the incident declared the evidence insufficient. The source hash and
saved investigation matched. Fixed evidence does not make model output
deterministic, and references written inside free-text reasons are not checked
by the structured citation validator. This is an observed failure, not an
accuracy estimate. Tests cover source validation, input separation, evidence
preservation, diagnosis failures, saving, exit codes, and overwrite protection.

After adding explicit instructions to support every part of a claim, one replay
per scenario returned `supported` diagnoses (about 80 seconds for the provider
case and 88 seconds for checkout). Both source hashes and investigations
matched their saved inputs. The provider root cause now cited the HTTP 503 logs,
and checkout described failure when `request.user` is None without assuming
authentication state. Incomplete citations remained: a provider claim combined
code changes and continued errors but cited only the commit, while a checkout
claim compared metrics with deployment timing but cited only metrics. The
provider limitations also inferred that no rollback occurred from a log entry
on the newer version, which does not establish rollback history. These are
mixed findings from individual runs, not evidence of reliable improvement.

An initial `qwen3:8b` provider replay completed in about 41 seconds, compared
with about 80 seconds for the preceding 4B replay on the same saved evidence.
Its diagnosis incorrectly framed the error spike as following the deployment:
the error rate was already 0.3 and provider failures were logged at 13:54,
before deployment at 13:57. It also treated the deployment as a possible cause
of the provider outage without accounting for those earlier failures. The
source hash and observations matched. This one attempt was faster but did not
demonstrate better diagnosis quality; model loading, generation length, and
runtime settings were not controlled for a performance benchmark. The default
model remained 4B for the repeated comparison below.

The first 8B checkout replay took about 34 seconds and returned
`insufficient_evidence`. It recognized that the diff matched the AttributeError
but required definitive causal proof and treated the gap between deployment
and the first observed error as a reason to abstain. Under this demo's rubric,
the evidence supports the narrower failure mechanism while reproduction and
exact onset remain limitations. Its description of the first error at 14:02
also conflated the metric sample with the log timestamp of 14:02:13; neither
establishes the exact onset.

The first 8B sparse-evidence replay took about 23 seconds and appropriately
abstained. It described deployment records and logs as unavailable, rather than
asserting no deployments or errors occurred, and requested relevant missing
observations. Both replay source hashes and investigations matched. Across
these three initial 8B attempts, sparse-evidence handling improved relative to
the observed 4B response, but the provider timeline and checkout abstention
remain concerns. These qualitative findings do not establish an overall winner
or a model-accuracy rate.

The first 8B provider replay with explicit settings (seed 42, 4096 context,
thinking enabled and the defaults above) completed in about 44 seconds. Its
settings and source hash were verified, but it returned `insufficient_evidence`
despite the observed provider-error mechanism. It raised a possible deployment
configuration change without supporting evidence and did not account for the
provider failures preceding deployment. This confirms the settings integration,
not an improvement in diagnosis quality.

### Repeated local model comparison

On 12 October 2026, comparison `31c65605-b81a-418c-b074-25f4716e4578`
ran both models against one saved investigation per scenario, using seeds
42, 43, and 44: 18 diagnosis replays in total. All completed. Every report's
source SHA-256, source run ID, incident, and investigation matched its original
report. All used context 4096, temperature 0.6, top-p 0.95, top-k 20, and
thinking enabled. The recorded runtime was Ollama 0.35.0, with model IDs
`359d7dd4bcda` (4B) and `500a1f067a9f` (8B), at project commit
`fc3efa669b5809bb09a325a44f747b307c7bf4dc`. These are short model IDs,
not full immutable digests.

| Scenario | Expected diagnosis status | 4B status matches | 8B status matches | 4B median diagnosis time | 8B median diagnosis time |
| --- | --- | --- | --- | --- | --- |
| Checkout regression | `supported` | 2/3 | 0/3 | 80.24 s | 19.55 s |
| Payment provider outage | `supported` | 1/3 | 0/3 | 84.12 s | 34.61 s |
| Sparse evidence | `insufficient_evidence` | 2/3 | 3/3 | 54.63 s | 16.76 s |

Status matches are not diagnosis-accuracy scores. Assistant inspection found
that 8B abstained in all nine attempts, including cases where the observations
support a specific failure mechanism without establishing its deeper cause.
Two checkout responses also treated a recorded rollback target as evidence of
a rollback action. Its sparse-evidence responses appropriately requested
missing records without claiming that no deployments or errors occurred.

4B remained inconsistent. Checkout seed 42 gave a supported explanation with
relevant citations and acknowledged that the conditions making `request.user`
None were unknown. Seed 43 had incomplete citations for compound claims.
The supported provider response omitted the pre-deployment failure timeline;
the two abstentions overlooked timestamps present in the evidence. Sparse
seed 43 labeled the error-rate increase itself a supported root cause while
admitting that its cause was unknown.

Keep 4B as the provisional default: this comparison does not justify switching
to 8B for diagnosis quality. 8B was faster in this sample, but each scenario
used only one evidence bundle and three seeds; model loading, output length,
and warm/cold state were not controlled. This is not a general performance
benchmark or a reliable accuracy estimate for either model.

Raw reports and environment metadata remain locally under
`out/comparisons/31c65605-b81a-418c-b074-25f4716e4578/`, which is excluded from
Git. These findings are an assistant inspection; no human review sidecars
were created, and the reports remain `not_scored`.

### Diagnosis prompt revision experiment

A follow-up comparison, `ee0df895-d512-45d1-8501-e888b4702f6d`, tested a
revised prompt with 4B on the same three saved investigations and seeds
42, 43, and 44. The revision distinguishes symptoms from failure mechanisms,
separates unknown deeper causes from missing causal evidence, and explains
that a rollback target does not establish an executed rollback.

All nine replays completed. Their source hashes, run IDs, incidents,
investigations, model tag, and generation settings matched the corresponding
4B baseline attempts. Ollama remained 0.35.0 and the recorded 4B model ID
remained `359d7dd4bcda`. The comparison directory also contains source snapshots
of `agent.py`, `settings.py`, and `replay.py`; these capture the uncommitted
prompt revision that its recorded Git HEAD alone does not identify.

| Scenario | Baseline status matches | Revised status matches | Baseline median diagnosis time | Revised median diagnosis time |
| --- | --- | --- | --- | --- |
| Checkout regression | 2/3 | 3/3 | 80.24 s | 79.12 s |
| Payment provider outage | 1/3 | 2/3 | 84.12 s | 70.45 s |
| Sparse evidence | 2/3 | 3/3 | 54.63 s | 51.38 s |

Expected-status matches increased from 5/9 to 8/9, but assistant inspection
found continuing grounding failures. Checkout seed 43 placed error rate 0.4
at 14:02, when the recorded value was 0.35; 0.4 was observed at 14:05.
It also omitted evidence needed for compound claims. Seed 44 asserted
unauthenticated users without evidence of authentication state. The two
supported provider responses described the outage as temporary without
recovery evidence and did not explain why the deployment fails to account
for the earlier errors. Provider seed 44 still abstained solely because the
provider's deeper cause was unknown.

All sparse-evidence responses now abstained, removing the baseline's
symptom-as-cause result in this sample. Some wording still blurred missing
deployment records with the absence of deployments. No revised response
claimed that a rollback occurred, but the baseline 4B responses had not made
that claim either; this experiment does not test whether the revision fixes
the observed 8B rollback confusion.

These are mixed findings from three seeds per case, not a demonstrated overall
quality improvement or an accuracy score. Timings remain descriptive, with
the same benchmark limitations noted above. The raw reports and source
snapshots are local under `out/comparisons/ee0df895-d512-45d1-8501-e888b4702f6d/`.
The first human review, for provider seed 42, met causal explanation but did
not meet deployment reasoning, evidence grounding, or uncertainty handling.
The checkout seed 43 review met causal explanation and uncertainty handling,
but did not meet deployment reasoning or evidence grounding. Sparse-evidence
seed 43 met evidence grounding and uncertainty handling; causal explanation
and deployment reasoning were not assessable from its available observations.
All nine review hashes and report identities were verified; the original reports
and three existing reviews were unchanged. Reviews are separate sidecars; the original
reports retain their `not_scored` assessment fields.

The completed review set has the following met/assessable counts:

| Scenario | Causal explanation | Deployment reasoning | Evidence grounding | Uncertainty handling |
| --- | --- | --- | --- | --- |
| Checkout regression | 2/3 | 2/3 | 0/3 | 1/3 |
| Payment provider outage | 3/3 | 0/3 | 1/3 | 0/3 |
| Sparse evidence | Not assessable | Not assessable | 3/3 | 3/3 |

Provider seed 44 recognized the HTTP 503 mechanism in its reason, so causal
explanation met the criterion even though its decision to abstain failed
uncertainty handling. Sparse seeds 42 and 44 were read in the context of
available observations and requests for missing data; their ambiguous wording
about deployments should still be made explicit as missing returned records.
Checkout failures included unsupported authentication state, incomplete
citations, and treating the first elevated metric sample as exact onset.

These judgments mix three guided human reviews and six AI reviews. They are
not an independent or blind evaluation, and the summary pools reviewer types.
Completing this review set does not establish general accuracy or improvement
over the baseline, which has not received equivalent complete rubric reviews.

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

For supported diagnoses, the CLI also displays each root-cause and supporting
claim beside its cited observations, including tool names, arguments, and
results. This view excludes tool-selection reasoning, lists unresolved IDs in
`missing_evidence_ids`, and rejects duplicate observation IDs. The full report
remains available for checking uncited evidence and limitations. A resolved
citation can still point to unrelated evidence; the reviewer must judge whether
the observations support every part of the claim. This display does not assign
verdicts or change model output. Tests cover ID-based lookup, missing and
duplicate IDs, and diagnoses without structured claims.

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

### Comparison review summaries

Summarize reviews across the nested replay directories of one comparison:

```powershell
python -m evals.review_summary out/comparisons/<comparison-id> --comparison
```

Comparison mode recursively discovers JSON reports, excluding `summary.json`
and `*.review.json`. It includes completed and failed version 2 diagnosis
replays and rejects malformed reports, unfinished runs, duplicate run IDs,
missing provenance, and missing or invalid explicit generation settings.
Non-JSON metadata and source snapshots are not included.

Reports are grouped by case, requested model tag, recorded source provenance,
and generation settings other than seed. Each group lists its seeds and
relative report paths, plus total, reviewed, unreviewed, and criterion counts.
The same review hash and identity checks and assessable-only denominators used
for batch reviews apply. Invalid reviews stop the summary; absent reviews
count as unreviewed. The command prints JSON without changing reports or
reviews, calling a model, or saving a summary file. Without `--comparison`,
the existing manifest-based batch behavior is preserved.

Use one experiment directory at a time. Prompt versions and resolved model
digests are not grouping fields, so combining different experiments under a
parent directory can merge incompatible attempts. Recorded source provenance
is used for grouping; this command does not independently verify the original
investigation file or its equality with the replay's copied observations.
Discovery counts files present, not an expected experiment matrix, so missing
attempts cannot be detected without a separate inventory.

The revised-prompt comparison `ee0df895-d512-45d1-8501-e888b4702f6d` initially
produced 9 total runs, 3 reviewed and 6 unreviewed. After the six requested
AI reviews, it has 9 reviewed and 0 unreviewed, in three scenario groups with
3 reviews each. A summary snapshot was saved separately at
`out/comparisons/ee0df895-d512-45d1-8501-e888b4702f6d/summary.json`.
Sparse evidence has null causal-explanation and deployment-reasoning rates
because all three judgments for those criteria are not assessable.
These rates describe the recorded reviews, not overall diagnosis accuracy.
The 187-test suite passed after adding comparison discovery, grouping,
integrity checks, and CLI coverage, including compatibility with batch mode.

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

The first repeated model comparison is complete; the evaluation milestone
remains in progress. Use its findings to target diagnosis grounding and
uncertainty handling, validate changes against the same saved evidence and
review rubric, then run fresh full-pipeline evaluations.
The remediation citation and timeline checks now cover the saved provider
failures and a misleading-citation regression. Broader causal validity remains
unproven, including whether recurring background errors can incorrectly block
a useful rollback. Keep deterministic software tests separate from live model
evaluations. Automated deployment of OpsPilot will follow once there is a
deployable service.
