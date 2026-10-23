# Milestone 9 review

## Scope and decision

The project handoff defines Milestone 9 as adding runbooks and historical incidents
using semantic retrieval / pgvector, after normal tools work. I consider that
bounded implementation scope complete. This is not a production-readiness claim
or a claim that RAG improves diagnosis accuracy.

I am keeping references opt-in. The default diagnosis path does not retrieve
references. The matched development comparison did not establish an overall
diagnosis benefit that justifies enabling retrieval by default.

## Implemented capabilities

- Three synthetic knowledge documents, catalog validation and passage splitting.
- Local embedding generation, model identity checks and source/index provenance.
- Persistent JSON and PostgreSQL vector storage with semantic ranking.
- Retrieval evaluation, including negative queries and Python/PostgreSQL parity.
- Optional diagnosis augmentation through the replay CLI, with recorded query,
  query version, passages, index identity, embedding identity and timing.
- Separate operational evidence IDs and reference-note IDs, generation-schema
  constraints and runtime membership validation.
- Bounded diagnosis output, duplicate-claim rejection and output-limit failure
  handling with usage preserved.

The latest user-reported full suite passed 548 tests with 22 database tests
skipped. Database integration checks passed at earlier checkpoints; I have not
claimed a fresh database-enabled full-suite run for this closeout.

## Matched development comparison

[Portable report snapshot](milestone-9-comparison.json) preserves all six report
payloads, original paths and original-file SHA256 hashes. Generated originals
remain under the ignored `out/` directory. Each pair was checked for equal
incident, source, investigation, model and settings. Reports do not capture exact
prompt/code fingerprints, so this is not full execution provenance.

Settings: Qwen3 8B, seed 42, context 8192, generation cap 2048, temperature 0.6,
top_p 0.95, sampling top_k 20, thinking enabled. Reference runs retrieve three
passages using query version 2. There is one run per variant for each of three
known synthetic cases; these are development observations, not held-out accuracy
estimates. Reference-specific instructions and schema constraints differ by mode.

| Case | Without references | With references | Assessment |
| --- | --- | --- | --- |
| Provider outage | Correct mechanism; deployment-order comparison cites only the deployment, omitting evidence for failure timing | Correct mechanism; ordering claim cites both logs and deployment | Local citation improvement, with overly strong paraphrasing in a reference note |
| Checkout regression | Correct candidate mechanism, but log-only claim identifies request.user more specifically than the log itself | Appropriate exception guidance; ambiguous None wording and incident timing placed in a runbook-only note | Mixed support and precision |
| Sparse evidence | Insufficient evidence with a complete explanation | Still insufficient, but explanation reaches 600 characters and ends mid-word; adds a qualified dependency hypothesis | Worse completeness; no fabricated supported root cause |

| Case | Baseline total seconds | Reference total seconds |
| --- | ---: | ---: |
| Provider outage | 26.46 | 61.99 |
| Checkout regression | 25.70 | 47.33 |
| Sparse evidence | 15.23 | 43.05 |

These individual elapsed times include retrieval for reference runs. They are
not stable latency benchmarks. All six attempts completed structurally; completion
does not mean their claims are fully grounded. No aggregate accuracy score was
computed from this manual comparison.

## Remaining limitations

- Retrieval returns passages even for negative or underspecified queries; there
  is no calibrated relevance-abstention policy.
- Reference context has no enforced token budget. A generation cap is not an
  input-budget check or a wall-clock timeout.
- Citation validation establishes membership, not semantic support. Reference
  notes can still mix general guidance and incident-specific assertions.
- Schema-valid output can contain incomplete prose, overclaims or paraphrased
  repetition. Historical oversized reports may fail current schema validation.
- Retrieval augmentation is integrated in diagnosis replay; it is not an
  autonomous investigation tool or a default full-pipeline feature.
- Exact prompt/schema fingerprints, broader held-out cases and repeated trials
  remain future evaluation work.

## Next milestone

Proceed to Milestone 10: expose existing operational integrations through MCP.
Start with one read-only tool and preserve the existing direct Python behavior
and tests. Do not expand remediation permissions as part of that first step.
