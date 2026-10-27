# Diagnosis grounding evaluation plan

Protocol: `grounding-baseline-v1`, prepared 27 October 2026.
This is a planned evaluation, not a results report.

The [source manifest](grounding-baseline-sources.json) records validated saved
investigations. Follow the [batch commands](grounding-baseline-run.md) to capture
runtime provenance and execute the planned attempts.

## Scope

Measure the current diagnosis stage on the three existing synthetic scenarios
before changing prompts or generation defaults. Reuse `evals.replay`,
`evals.review`, and `evals.review_summary`. The existing review schema has four
criteria and remains at `rubric_version: 1`; this document provides concrete
scoring guidance without changing its serialized format.

Start with diagnosis replay over one fixed, completed investigation per scenario.
Inspect and record each source report's hash and available observations before
running the batch. Use the same source for every repeat of that scenario. This
isolates diagnosis behavior; it does not measure investigation success or the
full web workflow. Do not silently supplement missing observations from fixtures.

## Planned configuration

| Setting | Value |
|---|---|
| Cases | `checkout_regression`, `payment_provider_outage`, `sparse_evidence` |
| Diagnosis model | `qwen3:8b` |
| Seeds | 42, 43, 44 |
| Context / generation limit | 8192 / 2048 |
| Temperature / top-p / top-k | 0.6 / 0.95 / 20 |
| Thinking | Enabled |
| Retrieved references | Disabled |
| Planned attempts | Nine: three seeds per case |

Record the exact source commit, working-tree changes if any, model digest,
Ollama version, source reports and their hashes, configuration, and this protocol
in a batch manifest. Seeds aid comparison but do not guarantee deterministic
outputs across software or hardware changes. Preserve failed attempts; retries
must be additional labeled attempts, not replacements.

## Review procedure

Review the diagnosis against the observations actually supplied to it. Use the
scenario reference answer as a guide, not as additional evidence available to the
model. Judge cited claims against their cited responses, not just other responses
in the report. Investigation model reasoning is not evidence.

For each criterion select `met`, `not_met`, or `not_assessable`, with a rationale
quoting the relevant claim and identifying the supporting or conflicting
observations. A missing diagnosis requires all four criteria to be
`not_assessable` under the existing schema. Unsupported positive assertions are
`not_met`, not `not_assessable`.

| Existing criterion | Scoring rule |
|---|---|
| `causal_explanation` | The explanation identifies the supported mechanism without inventing upstream causes. Correct abstention when no mechanism can be assessed is `not_assessable` here and evaluated under uncertainty. |
| `deployment_reasoning` | Any deployment attribution respects timestamps and the actual code change. With relevant collected deployment evidence, omitting a necessary causal distinction is `not_met`. If no deployment evidence or deployment claim exists, use `not_assessable`. |
| `evidence_grounding` | Every factual claim is supported at its stated specificity. Citations must support all parts of the attached claim. Check timestamp arithmetic and do not treat empty results as proof of absence. |
| `uncertainty_handling` | The diagnosis distinguishes observed symptoms from unknown causes, qualifies unsupported certainty, and abstains when observations cannot establish a mechanism. |

## Scenario expectations

### Checkout regression

The changed access is `request.user.customer_id`. A null `request.user` makes
that access fail; the diff does not establish that the change made the user null.
The AttributeError and changed access support the regression explanation when
both are present in the collected evidence.

Timestamp anchors from the fixtures:

- Deployment: 13:57:00 UTC.
- Error-rate sample 0.01: 13:55:00; sample 0.35: 14:02:00; sample 0.4: 14:05:00.
- Returned error log: 14:02:13, which is 5 minutes 13 seconds after deployment.
- The 0.4 sample is 8 minutes after deployment and 10 minutes after the 0.01 sample.

The 7-minute gap is between 13:55 and 14:02. It does not support a claim that
error rate reached 0.4 within 7 minutes of deployment. The first returned log is
not proof of the exact incident onset. A claim about deployment timing needs
deployment evidence as well as the relevant metric or log evidence.

### Payment-provider outage

PayBridge returns HTTP 503 during payment authorization. The returned failures
are at 13:54 on version 1.7.3 and 14:02 on version 1.7.4; deployment is at 13:57.
The first observed failure therefore precedes deployment by 3 minutes. The diff
adds logging and does not explain the onset. The provider's internal reason for
returning 503 remains unknown.

Do not infer provider database saturation, an application regression, or a proven
benefit from rolling back checkout. Evaluate rollback appropriateness separately
from diagnosis scores.

### Sparse evidence

Metrics show increasing error rates, while matching logs and deployments are
empty. The appropriate diagnosis is `insufficient_evidence`, identifying the
missing error details or other observations needed to distinguish causes.

Empty tool results do not establish that no errors or deployments occurred.
Invented code failures, provider failures, or commit hashes fail grounding. A
correct abstention can meet grounding and uncertainty while causal explanation
and deployment reasoning remain `not_assessable`.

## Reporting and completion

Keep model output unchanged and store reviewer identity and review method.
Disclose AI assistance if used; do not call it independent human validation.
Existing review sidecars bind reviews to source report bytes by SHA-256.

Report per-case and per-criterion counts of all three verdicts, with assessable
denominators for any rates. Show completion and failure counts separately so a
failed generation cannot disappear from the summary. Include latency and token
usage, noting warm-up and hardware context; nine attempts are not a reliable p95
benchmark or evidence of production accuracy.

The checkpoint produces a versioned manifest, preserved reports and reviews,
and a concise results document with concrete failure examples. Only then select
one failure for a focused regression check and matched before/after comparison.
Keep the original baseline intact. Broader scenarios and full-pipeline evaluation
are subsequent work.
