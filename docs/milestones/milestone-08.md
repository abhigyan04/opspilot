# Milestone 8 audit and completion planning

Archived from the root README on 27 October 2026. Commands assume the
repository root as the working directory. Historical next steps, test counts,
and measurements describe their original checkpoints, not current status.

[Archive index](README.md) · [Current milestone status](../milestone-status.md)

---

## Next milestone

### Milestone 8 audit — 19 October 2026

The bounded evaluation-framework checklist below is complete. The
[Milestone 8 baseline](../../docs/milestone-8-baseline.md) and its
[JSON snapshot](../../docs/milestone-8-baseline.json) collect the existing measurements,
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
references remain opt-in. See the [Milestone 9 review](../../docs/milestone-9-review.md)
and [portable six-report snapshot](../../docs/milestone-9-comparison.json) for results,
verification scope and limitations.
Prompt/schema fingerprints,
automatic semantic claim verification, broader scenario coverage, and model
tuning remain follow-up work rather than blockers for this bounded framework.

Milestone 10's bounded local implementation is complete, with an MCP server exposing all four existing
fixture-backed investigation tools over stdio. Subprocess client tests verify
tool discovery, input schemas, and response parity with the direct Python
functions. The async investigation loop accepts the MCP executor; existing
synchronous callers continue to use direct Python tools by default.
See the [Milestone 10 review](../../docs/milestone-10-review.md) for verification,
remaining limits, and the next milestone's scope decision.

MCP builds on direct integration experience; LangGraph follows demonstrated workflow
complexity. UI and deployment come after a deployable service exists. RAG is
not assumed to fix timestamp or citation errors by itself.

