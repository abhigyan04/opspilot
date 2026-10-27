# Diagnosis grounding baseline

Reviewed 27 October 2026 using `grounding-baseline-v1`.
**These are Codex AI assessments, not independent human validation.**
The [portable evidence bundle](grounding-baseline-results.json) contains all nine
original report texts, report hashes, review records, configuration, and counts.
No model output was corrected during review.

## Scope and provenance

Nine diagnosis-only replays used three fixed saved investigations and seeds
42, 43, and 44. All nine completed, with no retries or failed generations.
Source hashes and model settings matched the prepared manifest.

- Execution commit: `481647c7a4a205e9f5837435eb466d2a915a5f80`.
- The worktree was not clean: evaluation documentation was being prepared.
  The evidence bundle records the status and actual Python source hashes.
- Model: `qwen3:8b`, digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`.
- Ollama: `0.40.9`; context 8192; generation cap 2048; temperature 0.6;
  top-p 0.95; top-k 20; thinking enabled; retrieved references disabled.
- Inputs: [source manifest](grounding-baseline-sources.json).
- Criteria: [evaluation plan](evaluation-plan.md), existing review schema version 1.

This measures diagnosis on already-collected evidence, not investigation quality,
remediation appropriateness, or end-to-end web application accuracy. All
observations were identical across seeds within each scenario. The selected
inputs are familiar synthetic cases, not a held-out test set.

## Review counts

Each cell is **met / not met / not assessable**. Not-assessable results are
excluded from any assessable denominator, not treated as successful diagnoses.

| Scenario | Causal explanation | Deployment reasoning | Evidence grounding | Uncertainty handling |
|---|---|---|---|---|
| Checkout regression | 3 / 0 / 0 | 2 / 1 / 0 | 0 / 3 / 0 | 3 / 0 / 0 |
| Provider outage | 3 / 0 / 0 | 3 / 0 / 0 | 2 / 1 / 0 | 2 / 1 / 0 |
| Sparse evidence | 0 / 0 / 3 | 0 / 0 / 3 | 3 / 0 / 0 | 3 / 0 / 0 |

The dominant failure is claim-level support: a valid evidence ID may refer to a
response that supports only part of a sentence. All three checkout runs identify
the broad mechanism, yet none meets the stricter all-claims-grounded criterion.

## Concrete findings

- **Checkout, seed 42:** claims error rate reached 0.4 “within 7 minutes of the
  deployment.” Deployment is at 13:57 and the 0.4 sample is at 14:05: 8 minutes.
  The claim cites metrics only, omitting deployment evidence. A separate claim
  relates the log to the code change while citing only the log.
- **Checkout, seeds 43 and 44:** statements identifying the diff as the deployed
  change cite only the commit response. The deployment response is needed to
  establish that link. Seed 44 also compares the error with the code change while
  citing only the log.
- **Provider, seed 42:** a claim that metrics coincide with PayBridge errors cites
  only metrics; it needs the logs too. A deployment-to-code claim also omits the
  deployment response.
- **Provider, seed 43:** factual claims and citations pass this review, but the
  limitations never explicitly identify the unknown internal reason for the
  provider's 503 responses. This is scored as an uncertainty omission, not an
  invented provider cause.
- **Provider, seed 44:** meets all four criteria under this review.
- **Sparse evidence, all seeds:** correctly abstain, identify missing observations,
  and avoid inventing a failure mechanism. Causality and deployment attribution
  are not assessable; grounding and uncertainty are met.

## Interpretive decisions

These judgments require review rather than string matching. Minute-level
formatting such as 14:02 for 14:02:13, and “5 minutes” for 5 minutes 13 seconds,
was accepted as rounded prose. The seed-42 “within 7 minutes” upper bound was
not accepted because the observed sample is 8 minutes after deployment.

Checkout seed 44's “existence of the user attribute” is imprecise. Its explicit
limitation about the user object being None was used to interpret the intended
null-object mechanism. Sparse seed 43's “no deployments are recorded” was read
as scoped to supplied observations, not a claim that no deployments occurred.
Provider seed 43's uncertainty verdict applies the requirement to distinguish
the observed dependency symptom from its unknown internal cause. A subsequent
human review may disagree; preserve these initial assessments when comparing.

## Runtime observations

| Scenario | Completed | Mean diagnosis seconds | Total input tokens | Total output tokens |
|---|---|---:|---:|---:|
| Checkout regression | 3/3 | 24.41 | 6,111 | 2,591 |
| Provider outage | 3/3 | 24.49 | 6,558 | 3,107 |
| Sparse evidence | 3/3 | 16.09 | 4,149 | 2,075 |

These sequential local runs did not control model warm-up or capture hardware
utilization. They are descriptive measurements, not a reliable latency benchmark
or p95 estimate. Token totals cover diagnosis calls only.

## Next engineering checkpoint

Address the objectively verifiable deployment-interval failure first. Inspect the
existing deterministic timeline and deployment-timing payload, add a focused
regression check for the 13:57-to-14:05 interval, and make the calculated value and
its source evidence explicit to diagnosis generation where needed. Avoid a
scenario-specific answer or a rule that silently rewrites generated text.

Then run a separate matched nine-attempt batch with the same source evidence,
seeds, model identity, and generation settings. Compare all four review criteria
and retain this baseline unchanged. Temporal support work will not by itself
resolve every citation-completeness issue; those remain visible in the comparison.
