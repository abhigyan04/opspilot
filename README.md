# OpsPilot

An evaluation-driven incident investigation agent for the fictional Acme
Commerce platform. The agent investigates synthetic incidents through a bounded
loop, selecting operational tools with model-generated, validated arguments
and feeding their results back into subsequent decisions. It then generates a
structured diagnosis and validates its evidence references. A human can review
and approve a rollback candidate for in-memory simulation.

## Run locally

From the repository root, using Python 3.11 or newer:

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

New full-pipeline and diagnosis-replay reports include a `usage` object. Each
recorded model attempt has its stage, model tag, `input_tokens` (Ollama's
`prompt_eval_count`), and `output_tokens` (`eval_count`). Counts are captured
before JSON and citation validation, so a rejected response still contributes
its reported usage. A request exception records unknown counts and preserves
the original exception. These are server-reported counts, not billing or
hardware-utilization measurements.

Full-pipeline reports collect investigation and diagnosis usage together,
including the investigation's final model-selected `finish` call. Replays
count only newly generated diagnosis calls, never source-report usage. Empty
evidence that skips generation records no model attempt. Replay CLI output
also includes usage; full-pipeline CLI output includes the batch aggregation.

Per-run and batch summaries distinguish known token subtotals from complete
totals. A missing count makes its complete total null, while known counts are
retained. Batch summaries expose reports with and without usage, recorded model
attempts, and counted calls for each token direction. Failed runs contribute
their available counts. Older reports without usage are unknown, not zero.
An explicitly recorded zero-call run has zero totals.

Live replay `735038a9-5f3c-4b2d-acc4-b124d5bd5f36` verified one new 8B diagnosis
call with 2,175 input tokens and 863 output tokens. The saved report matched
the CLI output. The user reported 281 passing tests after batch aggregation,
covering failure preservation, replay isolation, missing counts, and legacy
reports. Live full-pipeline token totals have not yet been separately checked;
their collection and aggregation are covered by deterministic tests.

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

New investigation metrics also contain `tool_arguments` and `evidence_content`
assessments for registered case configurations. Argument matching uses
evaluation-only expectations for each tool and scenario. Missing recorded
arguments are unassessable and excluded from the match-rate denominator;
the report exposes that count. Unexpected tools and incorrect arguments do
not match. This does not measure redundant calls or prove a commit hash was
obtained from a prior observation.

Evidence assessment compares returned results against the current scenario
fixtures, ignoring list order but requiring complete matching records. A
partial result does not count as a complete expected result. Repeated calls
cannot inflate coverage. Expected empty lookups are counted separately from
nonempty results; neither a missing call nor an omitted result matches an
expected empty lookup. Argument matching and evidence matching are separate:
one can pass while the other fails. Custom case configurations remain explicitly
`not_scored` for these checks while retaining basic tool-name coverage.

An offline check of three saved investigations produced:

| Case | Source run | Argument matches | Nonempty results captured | Expected empty lookups matched |
| --- | --- | --- | --- | --- |
| Checkout regression | `7a3f5342-6a12-4b22-a70d-950ba3c501b6` | 4/4 | 4/4 | Not applicable |
| Provider outage | `88405562-a606-4f8a-b802-2c3257f6a562` | 4/4 | 4/4 | Not applicable |
| Sparse evidence | `9cff3260-9b7c-4ec1-8c4b-df481c08a876` | 3/3 | 1/1 | 2/2 |

The original report bytes remained unchanged; these checks did not overwrite
historical metrics or call a model. The user reported 304 passing tests after
integration. These results establish fixture-result capture, not causal
sufficiency or diagnosis accuracy: sparse evidence still lacks a supported
mechanism despite capturing all available fixture results. Grading uses current
fixtures, so changing fixtures can change historical reassessment results.
The new assessments are saved per run; batch summaries do not yet aggregate
their rates.

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

### Milestone 8 audit — 19 October 2026

The bounded evaluation-framework checklist below is complete. The
[Milestone 8 baseline](docs/milestone-8-baseline.md) and its
[JSON snapshot](docs/milestone-8-baseline.json) collect the existing measurements,
review coverage, source hashes, and known failures. This is framework completion,
not production readiness or achievement of a diagnosis-accuracy target.

| Handoff criterion | Current coverage | Remaining limit |
| --- | --- | --- |
| Multiple reproducible scenarios | Three deterministic fixture scenarios, configurable full runs, saved-evidence replay | Model responses remain variable; fixtures are synthetic. |
| Root-cause accuracy | Reference explanations and a manual causal-explanation rubric, with review summaries | No universal accuracy scalar; pipeline `diagnosis_accuracy` remains null. Status agreement alone is not correctness. |
| Correct tool usage | Typed arguments, tool-name coverage, per-call fixture argument matching | Does not measure redundancy or whether arguments were justified by earlier observations; missing arguments are unassessable. |
| Required evidence gathered | Exact expected fixture-result matching, with nonempty coverage and separate empty lookups | Capturing available fixtures does not establish causal sufficiency; comparison uses current fixture contents. |
| Unsupported claims | Citation-ID validation, claim-to-observation views, manual grounding reviews | Valid IDs do not establish semantic support; review coverage must accompany scores. |
| Remediation correctness | Offline expected action/service/version matching across saved diagnoses | This is proposal matching, not proof of causal appropriateness or recovery. |
| Safety violations | Tests plus a saved synthetic evaluation of approval enforcement, explicit decline, changed state, and repeated execution | A finite control suite, not a scenario-level safety violation rate. |
| Task success | Pipeline completion, separate recovery checks, and a linked simulated review-execution-recovery check | Recovery uses a matching static fixture; real incident resolution and causal recovery remain unmeasured. |
| Token use | Per-call collection, full-run and replay reports, batch totals with missing-data coverage | Server-reported counts; unavailable counts remain null. Live replay verified; full-pipeline aggregation tested with mocked calls. |
| Latency | Stage timings and batch means | Local loading and runtime variability are included; observations are not controlled benchmarks. |
| Cost where applicable | Local Ollama inference without a paid inference API | API cost is not applicable; electricity and hardware costs are not measured. |

### Bounded completion plan

1. **Complete: token-usage capture.** Investigation and diagnosis calls retain
   counts even when response validation fails. Reports and batch summaries
   preserve unknown counts and separate fresh replay usage from historical
   investigation usage. Tests and one live replay validate this checkpoint.
2. **Complete: fixture-specific tool and evidence assessment.** Per-run metrics
   distinguish matching arguments, captured nonempty results, and expected empty
   lookups. Expectations stay outside agent inputs. Tests and offline checks of
   all three scenarios validate the bounded measure, not semantic tool optimality.
3. **Complete: offline simulation evaluation.** A saved control report
   covers unapproved and approved execution, stale state, repeated execution,
   and three recovery outcomes. It also exercises explicit decline and passes
   an approved execution result into fixture-backed recovery verification.
   Dimensions remain separate; these checks do not establish real task success.
4. **Complete: compact baseline.** The linked snapshot covers all three scenarios,
   historical review coverage, proposal matching, simulation controls, telemetry,
   and known failures. Existing evidence was reused without a new model sweep.
   Selective improvement examples remain separate from aggregate review results.

Milestone 9's bounded RAG implementation is complete: the reference collection, loader, passage splitter,
local embeddings, cosine-similarity ranking, and a development retrieval
evaluation are implemented, along with local index provenance and persistence.
Saved-index retrieval checks query-time model identity. PostgreSQL import and
SQL ranking are implemented and tested. Both JSON-backed and PostgreSQL-backed
retrieval entry points are available. Diagnosis accepts optional retrieved
references, and replay can retrieve them from PostgreSQL on request. A matched
three-case development comparison did not establish an overall diagnosis benefit;
references remain opt-in. See the [Milestone 9 review](docs/milestone-9-review.md)
and [portable six-report snapshot](docs/milestone-9-comparison.json) for results,
verification scope and limitations.
Prompt/schema fingerprints,
automatic semantic claim verification, broader scenario coverage, and model
tuning remain follow-up work rather than blockers for this bounded framework.

Milestone 10's bounded local implementation is complete, with an MCP server exposing all four existing
fixture-backed investigation tools over stdio. Subprocess client tests verify
tool discovery, input schemas, and response parity with the direct Python
functions. The async investigation loop accepts the MCP executor; existing
synchronous callers continue to use direct Python tools by default.
See the [Milestone 10 review](docs/milestone-10-review.md) for verification,
remaining limits, and the next milestone's scope decision.

MCP builds on direct integration experience; LangGraph follows demonstrated workflow
complexity. UI and deployment come after a deployable service exists. RAG is
not assumed to fix timestamp or citation errors by itself.

### Milestone 10: read-only MCP investigation tools

`app.mcp_server.server` uses the MCP Python SDK v2 to expose:

- `search_logs(service, level)`
- `get_deployments(service)`
- `query_metrics(service, metric_name)`
- `get_commit(commit_hash)`

These tools read synthetic fixtures selected at server startup with `--scenario`:
`checkout_regression` (default), `payment_provider_outage`, or `sparse_evidence`.
Tool callers cannot select a scenario or filesystem path. Responses are returned
as structured content under `result`.
Unmatched log, deployment, and metric searches return an empty list; an unknown
commit returns null. No remediation actions are exposed.

The client launches the server with `python -m app.mcp_server.server` and
exchanges MCP messages over stdin/stdout. No listening port, Ollama instance,
or PostgreSQL connection is needed for this checkpoint.

Run the investigation, server, and client checks:

```powershell
python -m pytest tests/test_investigation_executor.py tests/test_mcp_client.py tests/test_mcp_server.py -q
```

`app.mcp_server.client.connect_local_tools(scenario="checkout_regression")`
forwards the scenario to the server and manages one subprocess connection
for multiple calls. Its `MCPToolExecutor.execute()` accepts an existing tool
decision and unwraps the structured response into the direct tool's result
shape. It preserves empty lists and missing commits, rejects unsupported tools,
tool errors, missing result envelopes, and invalid outer result shapes, and
propagates transport failures. It does not validate individual record fields
or automatically retry failed calls.

`investigate_async(..., tool_executor=executor.execute)` can run inside
`async with connect_local_tools() as executor`, using one MCP connection for
the investigation. Tool results retain the existing evidence IDs, observation
messages, and step-record format. Synchronous model selection runs in a worker
thread so it does not block MCP communication. Executor failures propagate.
The synchronous `investigate()` wrapper uses `asyncio.run`; callers already
inside an event loop should await `investigate_async()` instead. `data_dir`
applies only to direct tool execution; MCP uses the scenario configured when
opening the connection.

The reported checkpoint passed **32 focused tests** and **580 tests,
22 skipped** in the full suite. The skipped database checks remain opt-in.
Subprocess tests cover successful and unmatched lookups for all four tools,
malformed log-search arguments followed by a valid call, and a deployment-to-
commit sequence through the adapter on one connection. Stub-client tests cover
adapter failure handling. A scripted-decision investigation test uses the real
MCP subprocess, feeds deployment evidence into the next commit lookup, and
verifies the final investigation record.

The evaluation runner accepts `--tool-backend direct|mcp`, defaulting to
`direct`. MCP supports the three named scenarios using their standard fixture
directories; unknown scenarios and custom fixture directories are rejected.
Each attempt and batch
summary records `tool_backend`. MCP connection startup and shutdown are included
in investigation timing, and connection failures are recorded at that stage.
Diagnosis continues to use the existing model path.

Example live evaluation (requires Ollama):

```powershell
python -m evals.runner --case checkout_regression --runs 1 --tool-backend mcp --model qwen3:8b --num-ctx 8192 --num-predict 2048 --seed 42 --think
```

`--model` selects the diagnosis model; investigation tool selection retains its
existing model configuration. The reported runner checkpoint passed **53 focused tests**
and **593 passed, 22 skipped** in the full suite. Tests cover backend forwarding,
saved backend metadata, unsupported selections, and recorded connection failure.

On 23 October 2026, live checkout-regression run
`51f67ded-4203-405a-b8bf-94f79b137250` in batch
`b0804070-d105-44c9-9d70-9d0470cc38aa` completed with `tool_backend="mcp"`.
It collected metrics, deployments, commit details, and logs in four tool calls,
then stopped by model decision. Required-tool coverage, fixture argument match,
and nonempty-result coverage were all 1.0. Total time was 104.39 seconds
(74.84 investigation, 29.55 diagnosis). Usage recorded five Qwen3 4B
investigation selections and one Qwen3 8B diagnosis call.

This verifies live execution through the MCP backend for one synthetic case,
not a diagnosis accuracy improvement. Inspection found that the diagnosis
identified the relevant deployment and expression but described a missing
`user` attribute rather than `request.user` being `None`. A claim connecting
the exception to the refactor cited only the log, omitting the commit evidence.
Formal diagnosis assessment remains `not_scored`. The full report is stored
locally under `out/evals/` and is not included in this documentation.

The subsequent scenario-support checkpoint passed **18 runner/backend tests**
and **606 passed, 22 skipped** in the full suite. Server subprocess tests compare
all four tools with direct fixture results for each scenario. Scripted model
decisions also exercise the complete runner-to-MCP path for provider outage and
sparse evidence, checking observation messages and diagnosis inputs against the
selected fixtures. Diagnosis generation is stubbed in those tests. Live model
execution over MCP has so far been verified only for checkout regression.

### Milestone 11: LangGraph foundation

`app.agent.workflow.build_investigation_graph()` builds an async
`START -> prepare -> investigate -> diagnose -> propose -> END` graph around the existing agent
functions. It accepts a fixture directory, investigation step limit, diagnosis
model, diagnosis settings, a target service (default `checkout-service`), and
`tool_backend="direct"` or `"mcp"`.
Both finished and step-limited investigations
proceed to diagnosis; investigation exceptions stop execution.

Each node invocation creates a fresh usage collector and returns a plain
snapshot in state, separated under `usage.investigation` and `usage.diagnosis`.
Collectors are not stored in graph state or shared across runs. Usage from a
failed node is not yet preserved in returned state.

Direct Python tools remain the default. With MCP, each investigation node opens
its own subprocess connection for the selected scenario and closes it before
diagnosis. MCP requires one of the three standard scenario fixture directories;
unknown scenarios and custom directories are rejected. The graph remains separate
from the evaluation runner. It accepts an optional checkpointer; in-memory
failure recovery and SQLite recovery across separate processes are tested.
Approval pauses and a user-facing persistence CLI are not yet implemented.
The intended next capability is a workflow that can pause for approval and
resume later while preserving the existing remediation guards.

The user verified LangGraph **1.2.16**, successful imports, and `pip check` with
no broken requirements. The foundation checkpoint passed **4 workflow tests**
and **610 passed, 22 skipped** in the full suite. Tests use mocked agent calls
to verify state passing, configuration forwarding, failure propagation, and
usage isolation across repeated invocations of the same compiled graph. They
do not establish live model behavior or persistent recovery.

The subsequent graph backend checkpoint passed **10 workflow tests** and
**616 passed, 22 skipped** in the full suite. It exercises the real MCP
subprocess for all three scenarios with scripted tool selection and stubbed
diagnosis, verifies scenario-specific logs reach diagnosis input, and checks
rejection of unsupported backends and fixture directories. These are transport
and orchestration checks, not live model accuracy evaluations.

```powershell
python -m pytest tests/test_workflow_checkpoint.py tests/test_workflow.py -q
```

The checkpointing foundation passed **12 focused tests** and **618 passed,
22 skipped** in the reported full suite. With `InMemorySaver`, a failed diagnosis
can be resumed using `graph.ainvoke(None, config=...)` with the same checkpointer
and thread ID. The diagnosis node runs again from its beginning; the completed
investigation and its usage snapshot are retained without repeating its calls.
Checkpoint boundaries are between graph nodes, not individual investigation
tool calls.

An interleaved two-thread test verifies that completing one thread and resuming
the other preserves their separate evidence, diagnosis, usage, and pending work.
These tests mock agent calls and do not test simultaneous execution, recovery
after a process restart, or failed-attempt usage accounting. In-memory
checkpoints are lost when the process exits.

SQLite persistence uses `AsyncSqliteSaver` from
`langgraph-checkpoint-sqlite` (verified installed version **3.1.2**, with
`pip check` reporting no broken requirements). Callers keep its async context
open while using a graph compiled with that saver. Resume uses the same database
file and thread ID, with `None` as graph input and unchanged graph configuration.
The prepare node saves a versioned configuration containing the resolved fixture
directory, backend, step limit, diagnosis model, diagnosis settings, and target
service. Investigation, diagnosis, and proposal nodes check it before executing,
including when resuming skips preparation.
Changed configuration or pending legacy state without configuration is rejected
before those nodes perform work. Use the original configuration to resume, or a
new thread for a different configuration. This guard does not fingerprint fixture
contents, model weights, or code, and is not protection against deliberate state
modification. Reading an already completed checkpoint does not execute a guard.

The configuration-guard checkpoint passed **19 focused tests** and **625 passed,
22 skipped** in the reported full suite. Tests reject changed model tags,
diagnosis settings, step limits, backends, and fixture directories before a
pending diagnosis executes. Existing SQLite tests still resume successfully
with unchanged configuration.

The SQLite checkpoint passed **14 focused workflow tests** and **620 passed,
22 skipped** in the reported full suite. One test closes and reopens storage
with rebuilt graphs and verifies the completed diagnosis survives another reopen.
A separate-process test saves a failed diagnosis checkpoint, exits, and starts
a new Python process against the same file. Diagnosis completes without repeating
investigation, and the investigation usage snapshot is retained.

These tests use temporary SQLite files and scripted agent calls. They verify a
clean process exit after a handled failure, not an abrupt kill during a write,
concurrent writers, failed-attempt usage accounting, or live model recovery.

```powershell
python -m pytest tests/test_workflow_process_restart.py tests/test_workflow_sqlite.py tests/test_workflow_checkpoint.py tests/test_workflow.py -q
```

The proposal checkpoint passed **23 focused workflow tests** and **629 passed,
22 skipped** in the reported full suite. The proposal node validates the saved
diagnosis and reuses `build_rollback_proposal` with the target service and
collected steps. It returns either a serialized proposal with
`proposal_status="review_required"`, or null with `proposal_status="no_proposal"`.
Both paths currently end the graph. `review_required` is a result label, not an
approval interrupt, authorization, or execution.

Tests exercise the existing policy with a scripted supported diagnosis, an
insufficient-evidence diagnosis, and a different target service. They verify
proposal fields and that evidence remains unchanged. Configuration version 2
includes the service and rejects incompatible pending version-1 checkpoints;
service changes are also covered by the resume-guard tests.

### Offline simulation control report

Run the deterministic control evaluation without Ollama or infrastructure access:

```powershell
python -m evals.safety_runner
```

Use `--output-dir PATH` to choose the destination (default: `out/safety`). Each
report includes a unique run ID, UTC start time, code hashes (including the
recovery loader), a recovery-fixture hash, and individual results grouped into
approval, execution guards, recovery, and review workflow. The command
returns exit code 0 when all checks pass and 1 when a check fails. Unexpected
setup or write errors propagate rather than producing a successful report.

On 19 October 2026, report
`out/safety/ea6c8aaa-88e2-4cd9-8e80-2310bff8fc84.json` recorded 10/10 passing checks:

- Approval: unapproved execution blocked without mutation; approved execution
  changes the version and consumes approval (2/2).
- Execution guards: changed current version, changed rollback target, and
  repeated execution rejected without further state changes (3/3).
- Recovery: healthy measurements yield `recovered`, an unhealthy measurement
  yields `not_recovered`, and insufficient measurements yield `inconclusive` (3/3).
- Review workflow: explicit decline leaves state unchanged with no recovery
  result; approval executes the rollback and passes its result into recovery
  verification, which returns `recovered` for the matching checkout fixture (2/2).

The user-reported full test run passed 321 tests. Tests also deliberately bypass
guards or force incorrect recovery results to check that evaluation detects
failures. The execution-guard evaluator accepts a `ValueError` with unchanged
state; it does not validate the precise rejection reason. Its approved-execution
control is therefore important but does not prove every rejection is correct.

This is a control-check pass count, not diagnosis accuracy, a safety violation
rate across incidents, or task success. The linked workflow checks the actual
execution result against the fixture's service and version transition, but the
static measurements do not demonstrate that rollback caused recovery. Review
responses are supplied by the evaluator; no human approval or real infrastructure
action occurs during this command. Generated reports remain local artifacts
under `out/`.

### Milestone 9: local knowledge collection

The [knowledge catalog](data/knowledge/catalog.json) lists two synthetic
runbooks and one fictional historical incident. Their Markdown files live under
`data/knowledge/`, separately from evaluation fixtures in `data/scenarios/`.
The documents provide operational guidance without copying scenario-specific
commits, versions, timestamps, or expected diagnoses. Historical observations
are reference material, not evidence about a current incident.

[`load_documents`](app/retrieval/documents.py) validates catalog metadata and
loads UTF-8 Markdown into immutable document records. Each record retains its
stable document ID, type, title, relative source path, synthetic flag, text,
and SHA-256 hash of the exact file bytes. The loader rejects duplicate IDs or
resolved paths, blank titles or contents, unsupported document types, and
invalid paths. Resolved document paths must remain inside the knowledge root.
Missing files and decoding errors propagate rather than silently omitting data.

[`chunk_document`](app/retrieval/chunks.py) splits the current prose documents
at Markdown `##` headings. It retains opening text as an introduction, keeps
subheadings within their section, and skips empty sections. Each immutable
passage carries document metadata, its section, the source-file hash, and an ID
formed from the document ID, source hash, and passage position. Editing any part
of a document changes all its passage IDs; the IDs identify document versions,
not permanent anchors across revisions.

The three current documents produce 14 nonempty passages (5, 5, and 4), with
passage bodies ranging from 113 to 589 characters. The splitter has no length
limit and is not a general Markdown parser: heading-like lines inside fenced
code need handling before such documents are added. A splitter algorithm change
also requires index invalidation; document hashes alone do not version that code.

Retrieved passages must remain labeled as reference material, including when
the introduction disclaimer is not retrieved.

### Local embeddings

[`embeddings.py`](app/retrieval/embeddings.py) uses `embeddinggemma:300m` through
Ollama at `http://localhost:11434`, with 768-dimensional vectors and input
format version 1. Queries use `task: search result | query: ...`; passages use
`title: DOCUMENT TITLE — SECTION | text: ...`. Formatting is separate from
the original passage contents used for citations.

Prepare the local model:

```powershell
ollama pull embeddinggemma:300m
```

Ollama must be running for live embedding calls. Open the Ollama application or
run `ollama serve` in a separate terminal. The adapter rejects blank inputs,
incorrect vector counts or dimensions, nonfinite values, and zero vectors.
It requests `truncate=False`, makes no server call for empty batches, and lets
server errors propagate. Tests use fake clients and require no running server.

The user-reported suite passed 368 tests. The live smoke check then embedded all
3 documents' 14 passages and one query successfully, producing 14 passage
vectors and a query vector with 768 dimensions. This establishes that the
formatted embedding path works; it does not establish retrieval relevance.

Local JSON index persistence and pgvector storage are implemented below.
Optional diagnosis augmentation is implemented in replay. Index manifests identify the embedding
model digest, format version, and source contents.
The development retrieval evaluation below precedes agent integration.

### Passage ranking

[`rank_chunks`](app/retrieval/search.py) normalizes query and passage vectors,
ranks by descending cosine similarity, and uses chunk IDs to break equal-score
ties deterministically. Hits retain the full passage metadata for later citation.
The ranker validates vector values and dimensions, chunk/vector counts, unique
chunk IDs, and positive integer `top_k`. It does not call Ollama.

The user-reported suite passed 386 tests. A live exploratory search over the
14 passages returned the following results with `top_k=3`:

| Query topic | Highest-ranked passage | Score | Other observations |
| --- | --- | --- | --- |
| Upstream HTTP 503 | Dependency errors / Symptoms | 0.5733 | Investigation ranked second; all three hits came from the dependency runbook. |
| AttributeError involving None | Application exceptions / Symptoms | 0.5631 | Investigation ranked second; all three hits came from the exception runbook. |
| Inventory reservation timeouts | Inventory incident / Historical observations | 0.7063 | All three hits came from the historical incident. |
| Chocolate cake | Application exceptions / Investigation | 0.1299 | All returned passages were unrelated to the query. |

These four queries are a smoke check, not a retrieval benchmark or diagnosis
accuracy result. Similarity is not a relevance probability. The ranker always
returns up to `top_k` hits when passages are available, even for unrelated
queries; no relevance threshold or abstention policy is calibrated yet. The
symptom matches rank above investigation guidance in the two runbook examples,
so document-level matching alone is insufficient to measure useful retrieval.

### Retrieval development evaluation

```powershell
python -m evals.retrieval_runner --top-k 3
```

The runner embeds the collection once, evaluates eight queries, and saves a
report under `out/retrieval/` (`--output-dir` overrides the destination).
Expectations in `evals/retrieval_cases.py` identify document/section pairs and
are used only for scoring, not supplied to the retriever. Six positive cases
include paraphrases; two negative cases cover cooking and unsupported production
database details. This small authored development set is not held-out evidence
of generalization.

Report `ef6a523e-7ed4-4bb8-a2cc-1978248f3e96` completed with `top_k=3`:

| Measure | Result |
| --- | --- |
| Positive queries with an expected section in top 3 | 6/6 (hit rate 1.0) |
| Mean expected-section recall at 3 | 1.0 |
| Mean reciprocal rank at 3 | 0.8333 |
| Negative queries returning passages | 2/2 |

The first relevant section ranked second for `dependency_investigation` and
`exception_investigation`, and first for the other four positive cases. Both
expected inventory sections appeared in its top three. Negative cases are
excluded from positive-case averages; their highest scores were 0.1408 for
cooking and 0.3911 for unsupported database details. The latter demonstrates
that topical similarity does not establish answerability. No relevance cutoff
has been calibrated, and the report does not measure diagnosis improvement.

Reports retain per-query ranks and judgments, passage text and metadata, source
hashes, code hashes, model tag, format version, and elapsed time. The installed
model digest is not yet recorded by this evaluation runner (the index preparation
path below does record it). `completed` means the evaluation ran, not
that retrieval met a quality threshold. Errors propagate without saving an
incomplete report as completed. The user-reported suite passed 407 tests;
runner tests use fake embeddings and do not require Ollama.

### Local index preparation and reuse

[`prepare_index`](app/retrieval/prepare.py) loads the current collection, creates
passages, and obtains the exact configured model tag's digest from local Ollama.
The manifest includes model identity, dimensions, embedding format version,
chunking version, and complete ordered passage records. Its deterministic
fingerprint names the JSON index file inside the caller's chosen directory.
Changes to these inputs select a different file rather than overwriting an old
index. Increment the chunking or formatting version when those algorithms change.

```python
from pathlib import Path
from app.retrieval.prepare import prepare_index

index = prepare_index(Path("out/indexes"))
print(index.path, index.reused, len(index.chunks))
```

A matching index loads vectors without embedding the passages again. Ollama
must still be running: preparation checks model identity before and after the
operation. An observed identity change prevents a newly built index from being
saved. This detects changes across the operation but does not lock the model
registry. The retrieval entry point below adds a check after query embedding.

The index loader checks payload integrity, the expected manifest, vector counts,
dimensions, finite numeric values, and nonzero vectors. Corrupt files raise an
error rather than triggering silent replacement. Hashes detect accidental edits,
not malicious modification with recomputed hashes. Exclusive file creation
prevents overwrites; writes are not atomic, and an interrupted write can leave
an invalid file that must be handled explicitly.

The user-reported suite passed 450 tests. The live smoke check built and then
reused 14 passage vectors of 768 dimensions under
`out/indexes/85e42b4b-ac69-4cb5-af3c-167ea0f9abc3/` with manifest fingerprint
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695`.
The model digest was
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
The saved file's integrity and vector shape were checked separately without
calling Ollama. Generated indexes remain local under ignored `out/`.

### Search a saved index

[`retrieve`](app/retrieval/retrieve.py) validates the query and `top_k`, prepares
or reuses the matching passage index, embeds the query, and checks model identity
again before ranking. Observed identity changes raise an error instead of
returning results that may mix incompatible vectors. These before/after checks
do not lock the model registry against concurrent updates.

```python
from pathlib import Path
from app.retrieval.retrieve import retrieve

result = retrieve(
    "What should I investigate when a dependency returns HTTP 503?",
    Path("out/indexes"),
    top_k=3,
)
print(result.index_reused)
for hit in result.hits:
    print(hit.chunk.document_id, hit.chunk.section, hit.score)
```

Repeated searches in the same directory reuse passage vectors while generating
a fresh query vector. The result includes index path, reuse status, embedding
identity, and ranked hits with citation metadata. Ollama is still required for
identity checks and query embedding.

The user-reported suite passed 458 tests. A live search reused the index under
`out/indexes/85e42b4b-ac69-4cb5-af3c-167ea0f9abc3/` for the development query about
upstream 503 errors and deployment reasoning. Dependency-runbook sections ranked
Symptoms (0.5055), Investigation (0.4806), and Response considerations (0.3859),
matching the earlier evaluation's order and scores to four decimal places.
This validates the reuse path for one query, not general retrieval quality or
diagnosis improvement. No relevance cutoff or abstention policy is applied.

### Local PostgreSQL and pgvector

[`docker-compose.yml`](docker-compose.yml) runs PostgreSQL 17 with pgvector
0.8.7 using `pgvector/pgvector:0.8.7-pg17-bookworm`. The published port is
`127.0.0.1:5433`, mapped to container port 5432. The database and user are
`opspilot`; `opspilot_local_dev` is the explicit local development password.
This setup uses the image's bootstrap database user, not a production
least-privilege application role.

```powershell
docker compose config --quiet
docker compose up -d --wait postgres
docker compose ps
docker compose exec -T postgres psql -U opspilot -d opspilot -v ON_ERROR_STOP=1 -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

The named `postgres_data` volume persists database files across container
recreation. [`001_enable_vector.sql`](infra/postgres/init/001_enable_vector.sql)
enables the extension during first initialization. Initialization scripts run
only for a new database volume; adding later SQL files does not automatically
apply them to an existing database. Subsequent schema changes must be applied
explicitly.

The user verified a healthy container, extension version `0.8.7`, and cosine
distance 0 for two identical vectors. These checks establish database and
extension availability. Retrieval tables and schema integration tests are now
implemented below, together with passage import and SQL ranking. The high-level
`retrieve()` function still uses the JSON index.

Stop the service while preserving data with:

```powershell
docker compose stop postgres
```

`docker compose down -v` removes the database volume and its data; it is not
needed for normal startup, shutdown, or schema updates.

### Retrieval schema and database tests

Apply [`001_retrieval_tables.sql`](infra/postgres/migrations/001_retrieval_tables.sql)
once to an initialized database:

```powershell
Get-Content -Raw infra/postgres/migrations/001_retrieval_tables.sql |
    docker compose exec -T postgres psql -U opspilot -d opspilot -v ON_ERROR_STOP=1 -f -
```

The migration creates `retrieval.indexes` for manifests and expected passage
counts, and `retrieval.passages` for metadata and `vector(768)` embeddings.
Passages reference an index fingerprint; chunk IDs and positions are unique
within each index. Constraints reject invalid metadata, zero vectors, and
missing parent indexes. Pgvector enforces vector dimensions and finite values.
The migration runs in a transaction and intentionally fails if its tables
already exist. There is not yet an automated migration-history mechanism.

Python connects through the `psycopg[binary]` project dependency. The user
verified connectivity to `opspilot`, extension version 0.8.7, and both tables.
The schema does not itself prove that a manifest matches its fingerprint or
passages, or that all expected passages exist. The importer validates its input
file against the caller's expected manifest and inserts all rows atomically;
SQL search also checks stored metadata and passage counts.

Database tests require an explicit connection string:

```powershell
$env:OPSPILOT_TEST_DATABASE_URL = "postgresql://opspilot:opspilot_local_dev@127.0.0.1:5433/opspilot"
python -m pytest tests/test_pg_schema.py -q
python -m pytest -q
Remove-Item Env:OPSPILOT_TEST_DATABASE_URL
```

Use the local development database for these tests. Each test rolls back its
temporary records, including on failure. Without the variable, database tests
skip; with it set, connection errors fail rather than skip. The verified
user-reported results were 458 passed / 10 skipped without configuration,
10 passed for the schema tests alone, and 468 passed for the configured full
suite. Existing CI does not configure this database, so those integration tests
remain skipped there.

### PostgreSQL import and search

[`pg_store.py`](app/retrieval/pg_store.py) provides `import_index()` and
`search_index()`. Both require an expected manifest supplied by the caller.
Import validates the saved JSON index, requires 768-dimensional vectors, and
inserts the manifest and ordered passages in one transaction. An insertion
failure rolls back the entire import; duplicate index fingerprints raise an
error rather than overwriting existing data. Within an existing transaction,
the importer uses a savepoint and leaves the outer commit to its caller.

SQL search scopes results to the manifest fingerprint, checks stored manifest
metadata and passage count, validates the query vector, and verifies returned
passage metadata against the expected records. It ranks by cosine similarity
(`1 - cosine distance`) with chunk-ID ties sorted using the `C` collation.
No approximate vector index or relevance cutoff is used. These checks do not
revalidate every stored vector's provenance or lock against concurrent database
edits. The caller still owns query-model compatibility checks.

The live import reused the local index with fingerprint
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695` and stored all
14 expected passages. A subsequent shared-query-vector smoke check found the
same three dependency-runbook passages as Python, in the same order, with scores
matching within `rel_tol=1e-5, abs_tol=1e-6`. Pgvector stores single-precision
values, so small differences are expected. This was one-query parity validation,
not a full database-backed retrieval evaluation.

The user-reported importer/search integration suite passed 12 tests and the full
database-enabled suite passed 480 tests. Tests cover atomic rollback, duplicate
imports, stale manifests, ranking, missing/incomplete indexes, changed returned
content, tie order, and invalid query vectors. All test records are rolled back.

### PostgreSQL retrieval orchestration and development parity

[`retrieve_postgres`](app/retrieval/pg_retrieve.py) builds the expected manifest
from current documents, passages, and the installed embedding model identity.
It embeds only the query, rechecks model identity, and calls SQL search for the
matching imported index. It does not import data or generate passage embeddings
during a search. Missing indexes and observed model changes raise errors. The
caller supplies and owns the database connection; the function does not commit
or close it. As with JSON-backed retrieval, identity checks do not lock Ollama's
model registry against concurrent changes.

The user-reported normal suite passed 466 tests with 22 database tests skipped
after adding this entry point. Its eight orchestration unit tests use fake
backends; the live checks below separately exercise PostgreSQL and Ollama.

Saved development report `out/retrieval/8508ffc5-edff-4bfa-9b48-a7cf46a4dbf7.json`
evaluated all eight queries through PostgreSQL against index
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695`:

| Measure | PostgreSQL result |
| --- | --- |
| Positive queries with an expected section in top 3 | 6/6 |
| Mean expected-section recall at 3 | 1.0 |
| Mean reciprocal rank at 3 | 0.8333 |
| Negative queries returning passages | 2/2 |

Comparison with Python report `ef6a523e-7ed4-4bb8-a2cc-1978248f3e96` verified
identical queries, expected sections, ordered top-three chunk IDs, and relevance
judgments for every case. All 24 scores matched within `rel_tol=1e-5,
abs_tol=1e-6`; the largest absolute difference was approximately `9.79e-8`.
This establishes parity on this small development set, not new relevance gains,
held-out generalization, or diagnosis improvement. Both negative queries still
return passages because no abstention filter is applied.

The PostgreSQL report was produced by a one-off evaluation script and records
the model identity and index fingerprint, but not the full code hashes captured
by the existing Python runner. A reusable database evaluation CLI is not yet
implemented. Generated reports remain local artifacts under `out/`.

### Optional references in diagnosis

[`build_reference_context`](app/retrieval/context.py) converts ordered search
hits into reference records with full passage text, source metadata, and
`reference:<chunk_id>` identifiers. It rejects duplicate chunk IDs and blank
content. Similarity scores are excluded from diagnosis input because retrieval
similarity is not diagnostic confidence.

[`generate_diagnosis`](app/agent/agent.py) accepts an optional `reference_hits`
argument. Nonempty references are supplied separately from operational
observations. The prompt treats them as untrusted background guidance for
hypotheses, not current-incident evidence or instructions to execute.

Operational citation IDs remain the only IDs allowed in `evidence_ids`, and
runtime validation rejects reference IDs used as evidence citations. With no
operational steps, diagnosis still returns `insufficient_evidence` without a
model call, even when references are available.

Both diagnosis statuses now support a separate `reference_notes` list for
background guidance. Each note contains a statement of up to 600 characters and
one to three `reference_ids`; at most three notes are allowed. Older diagnoses
without this field default to an empty list, which appears in newly serialized
output. Root cause and supporting claims still require operational `evidence_ids`.

The generation schema restricts reference citations to supplied passage IDs.
Without references it permits zero notes. Runtime validation independently
rejects unknown reference IDs, including operational evidence IDs used in notes,
for both supported and insufficient-evidence diagnoses. The prompt directs
runbook guidance into reference notes rather than operational claims. These
checks establish citation membership and separation, not whether a cited source
actually supports the statement.

The reference-note integration checkpoint passed **548 tests, 22 skipped** in
the user-reported full suite. Live provider-outage replay
`8dc79d7b-f131-4fdd-843c-853446eed920` (under the comparison directory's
`reference-notes/` folder) used identical investigation data, reference context,
and model settings to bounded replay `830a0606-6fe9-4585-9110-e34b56d081b0`.
It returned three operational supporting claims and two separate reference notes.
The notes cited the dependency runbook's Symptoms and Investigation passages;
the prior misuse of the logging diff to cite runbook guidance was absent.
It retained correct metric values, failure-before-deployment ordering, and an
explicit unknown provider cause, without importing the inventory incident's cause.

This is a single-case citation-separation improvement after changing both schema
and prompt, not an aggregate accuracy result or proof of RAG's benefit over a
matched no-reference baseline. The Symptoms note paraphrased the source more
strongly than its conditional wording, and the note text redundantly included
long citation IDs. The run reported 1,207 output tokens and 47.98 seconds for
diagnosis, below the configured 2,048-token generation cap.

The reported checkpoint passed 34 focused diagnosis tests and the full suite
with **475 passed, 22 skipped**. The skipped checks require the opt-in database
test URL. Tests cover reference serialization, separate payloads, citation
validation, and the no-observations guard. They do not establish model resistance
to instructions embedded in references or improved diagnosis accuracy.

Reference input currently has no token budget or relevance-abstention filter.
Controlled comparisons remain necessary before claiming diagnosis improvement.

### Replay with PostgreSQL references

The replay CLI supports opt-in retrieval using query version 2 from
[`build_retrieval_query`](app/retrieval/query.py). It searches with up to three
distinct ERROR/CRITICAL log messages in observation order, normalizing whitespace
and limiting each message to 300 characters. When a record omits its level, the
requested log level is used. Without usable messages, it falls back to normalized
incident text limited to 400 characters, without an added label. These are query
character limits, not a diagnosis token budget. Previous model reasoning,
diagnoses, and expected answers are not used as retrieval queries.
The database must already contain the index matching the current knowledge
collection and embedding identity; replay does not import or rebuild it.

```powershell
docker compose up -d --wait postgres
$env:OPSPILOT_DATABASE_URL = "postgresql://opspilot:opspilot_local_dev@127.0.0.1:5433/opspilot"
python -m evals.replay <saved-report.json> --model qwen3:8b --seed 42 --num-ctx 4096 --think --with-references --retrieval-top-k 3
Remove-Item Env:OPSPILOT_DATABASE_URL
```

Replace `<saved-report.json>` with a version 2 investigation report. Ollama must
be running with the diagnosis and embedding models available. The URL shown is
for the local development Compose service. This command reads the process
environment, not an `.env` file. `OPSPILOT_TEST_DATABASE_URL` remains the separate
opt-in setting for database tests.

Without `--with-references`, replay does not connect to PostgreSQL.
`--retrieval-top-k` controls passage count; `--top-k` controls model sampling.
The CLI owns and closes the connection. A connection failure exits with code 1
before creating a report. Retrieval and diagnosis failures inside replay are
saved with their respective error stages.

Saved reports include the supplied `reference_context` separately from the
unchanged investigation. PostgreSQL runs also record the retrieval query,
query version and strategy,
requested passage count, index ID, embedding identity, ordered chunk IDs and
scores, and retrieval duration. Scores are not passed to diagnosis. Reference
context is retained on diagnosis failure; its presence records supplied input,
not proof that the model used it. CLI output is a compact summary; inspect the
saved report for the reference context and retrieval metadata.

The reported CLI checkpoint passed **37 replay tests**, with **486 passed,
22 skipped** in the full suite. These tests mock database and model calls;
they verify orchestration and reporting, not diagnosis accuracy.

The subsequent query-version-2 checkpoint passed **50 focused query/replay
tests**, with **499 passed, 22 skipped** in the full suite. Database checks remain
opt-in. Retrieval-only development comparisons on checkout regression and
provider outage used the same index and embedding identity. Error-only queries
ranked the respective runbook's Symptoms section first and Investigation second.
With incident-plus-error queries, inventory history ranked first; checkout's
application Investigation section was absent from the top three, and dependency
Investigation ranked third for provider outage. Less relevant historical material
still appeared at rank three with error-only queries.

This is a retrieval improvement on two known development cases, not held-out
generalization or demonstrated diagnosis improvement. Query version 2 has not
established an overall diagnosis accuracy gain. No relevance-abstention policy is
implemented, and sparse evidence can still retrieve unrelated references.

### Bounded diagnosis generation

Diagnosis generation now supplies a positive `num_predict` limit, defaulting to
2,048 tokens. Both `evals.replay` and `evals.runner` accept `--num-predict`; the
effective value is recorded in diagnosis settings. This controls diagnosis
generation only, not investigation tool-selection calls. It is not a wall-clock
timeout or a guarantee that the input and output fit within `num_ctx`.

A response with `done_reason="length"` raises `DiagnosisGenerationLimitError`
before JSON parsing, even if its content could be parsed. Usage is collected
first. Replay saves the attempt as a diagnosis-stage failure with no accepted
diagnosis, retaining the investigation and available token counts. It does not
automatically retry.

The diagnosis schema also limits supporting claims to six, limitations to four,
missing-evidence items to six, and citation IDs per claim to twelve. Claim text,
limitations, the insufficient-evidence reason, and missing-evidence items are
limited to 600 characters each. Runtime validation rejects duplicate statements
across the root cause and supporting claims after case and whitespace
normalization. This does not detect paraphrases or verify factual support.
Oversized historical diagnoses may therefore fail validation under the current
schema; saved artifacts are not rewritten.

The reported checkpoint passed **54 focused generation-limit/replay tests** and
**527 passed, 22 skipped** in the full suite. Offline tests verify option
forwarding, schema bounds, duplicate rejection, and a saved limit-termination
failure with usage preserved and no retry. These controls bound accepted output
and request generation limits; they do not establish improved diagnosis accuracy.

A subsequent live provider-outage replay (`830a0606-6fe9-4585-9110-e34b56d081b0`,
under `out/comparisons/40359ea0-b6fa-47a6-aa13-f3b4cb71084a/bounded-ctx8192/`)
completed with Qwen3 8B, an 8,192-token context, and a 2,048-token generation cap.
It reported 899 output tokens, six supporting claims, four limitations, and
43.76 seconds for diagnosis. The user reported 100% GPU placement at that context.
This run avoided the previous repetition loop, but did not hit the token cap,
so live limit-termination handling remains untested. Schema and generation limits
changed together; their individual effects cannot be isolated from this run.
The diagnosis still cited the logging diff for a general dependency-pattern
claim, so semantic citation support remains unresolved.
