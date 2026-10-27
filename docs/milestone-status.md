# Milestone status

Snapshot: 27 October 2026. This page describes the current delivery scope;
individual milestone reviews retain their historical measurements and limits.

| Milestone | Delivered scope | Boundary |
|---|---|---|
| 1–4: deterministic tools and investigation | Synthetic scenarios, structured arguments, bounded iterative investigation | No production integrations |
| 5: evidence-backed diagnosis | Structured output and runtime citation checks | Citation validity does not establish diagnosis accuracy |
| 6: human-approved remediation | Proposal checks and a separate approved in-memory simulation | Web approval records a decision only |
| 7: verification | Recovery classification using synthetic post-action observations | Not integrated into the persisted review graph |
| 8: evaluation | Tool, evidence, safety, remediation, usage, and timing evaluation infrastructure | Historical measurements are not a current aggregate accuracy benchmark |
| 9: RAG | Provenance, embeddings, local/pgvector search, retrieval evaluation, opt-in diagnosis replay | Not enabled in the live workflow; no overall benefit established by the small comparison |
| 10: MCP | Validated local stdio investigation tools and selectable executor | Synthetic read-only tools, not production connectors |
| 11: LangGraph | SQLite checkpoints, restart coverage, proposal review interrupt, CLI | Graph ends after review; no durable action execution |
| 12: UI and deployment | FastAPI UI, responsive light/dark themes, Docker, CI, public recorded demo | Live inference stays local; GitHub Pages serves static outputs |

## Evidence

- [Evaluation baseline](milestone-8-baseline.md)
- [RAG review and comparison](milestone-9-review.md)
- [MCP review](milestone-10-review.md)
- [Persisted workflow review](milestone-11-review.md)
- [Local UI and deployment review](milestone-12-review.md)
- [Reproducible demo procedure](milestone-12-demo.md)
- [Public recorded demo](https://abhigyan04.github.io/opspilot/)
- [Verified deployment run 40459778780](https://github.com/abhigyan04/opspilot/actions/runs/40459778780)
  for commit `0cd1572434c6a49281dd811e485236cee85d89ef`

The latest developer-reported local suite result was **720 passed, 22 skipped**.
The skipped checks require PostgreSQL configuration; this count does not claim
those checks ran in that invocation or measure model diagnosis accuracy.
The deployment run above is a specific verified historical run, not a claim
about CI for every later commit.

## Next checkpoint

Establish a current diagnosis-grounding baseline across checkout regression,
payment-provider outage, and sparse evidence. Existing citation checks validate
IDs, but known timing and causal-reasoning errors show why semantic assessment
is also needed.

1. Define evidence-based review criteria for each scenario: causal attribution,
   deployment ordering, timing arithmetic, unsupported claims, and appropriate
   uncertainty when evidence is missing.
2. Use the existing evaluation and replay tools to collect repeated runs with
   fixed model settings and recorded seeds. Record the source commit, model
   identity, inputs, and outputs so comparisons are reproducible.
3. Score diagnosis quality separately from pipeline completion, citation
   validity, and remediation appropriateness. Report failures alongside latency
   and token usage; keep full-pipeline and diagnosis-only results separate.
4. Select a demonstrated failure, add a focused regression check, and compare
   the fix against the same baseline before changing defaults.

This checkpoint is complete when a versioned report documents the configuration,
review criteria, per-case results, and remaining failures. A small synthetic
evaluation should not be presented as production accuracy. Broader scenarios
and durable execution with recovery verification remain subsequent work.
