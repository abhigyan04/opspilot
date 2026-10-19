# Milestone 8 evaluation baseline

Snapshot: 19 October 2026. I assembled this baseline from existing local reports
without new model calls. The [JSON snapshot](milestone-8-baseline.json) preserves
the measurements, source paths and SHA-256 hashes, fixture hashes, and assessment
code hashes. It is a portable summary; the original reports under `out/` remain
local and are not bundled here.

This closes the bounded evaluation-framework checklist in the README. It does
not establish production readiness or a diagnosis-accuracy target. These results
come from different checkpoints and must not be treated as one controlled model
comparison. The latest user-reported suite passed 321 tests.

## Investigation coverage

I rescored one saved investigation per scenario against the current fixtures.
All three investigations stopped normally and covered every required tool.

| Scenario | Matching tool arguments | Captured nonempty result groups | Matched expected empty lookups |
| --- | --- | --- | --- |
| Checkout regression | 4/4 | 4/4 | Not applicable |
| Payment provider outage | 4/4 | 4/4 | Not applicable |
| Sparse evidence | 3/3 | 1/1 | 2/2 |

These are exact fixture comparisons, not causal sufficiency or optimal tool use.
Empty lookups do not establish that no relevant events occurred. The provider
investigation here is newer than the one used for the historical reviews below.

## Historical diagnosis reviews

Comparison `ee0df895-d512-45d1-8501-e888b4702f6d` contains nine Qwen3:4b replays:
three scenarios, seeds 42/43/44, context 4096, temperature 0.6, top-p 0.95,
top-k 20, and thinking enabled. All nine have review sidecars; none are unreviewed.
I recomputed the summary with the existing review loader and confirmed it matches
the saved summary. Six reviews were AI-assisted, as recorded in the README;
these are rubric judgments, not independently adjudicated ground truth.

Each fraction is criteria met / assessable reviews:

| Scenario | Causal explanation | Deployment reasoning | Evidence grounding | Uncertainty handling |
| --- | --- | --- | --- | --- |
| Checkout regression | 2/3 | 2/3 | 0/3 | 1/3 |
| Payment provider outage | 3/3 | 0/3 | 1/3 | 0/3 |
| Sparse evidence | N/A (3 unassessable) | N/A (3 unassessable) | 3/3 | 3/3 |

The main recorded weaknesses are unsupported claims, deployment reasoning, and
overconfidence. Valid citation IDs and complete evidence capture do not prove
that claims follow from observations. These historical results do not score the
latest prompt or establish Qwen3:8b performance. Selective later improvement
examples are not pooled into this table. `diagnosis_accuracy` remains null.

## Remediation and simulation

Saved proposal evaluation `1e6f3ef2-3d61-4123-928e-4c4b4ea2b898` matched expectations
for 9/9 historical diagnoses: 3/3 per scenario. Checkout expects a rollback
candidate; provider outage and sparse evidence expect abstention. This measures
proposal matching, not diagnosis correctness or recovery.

Control report `ea6c8aaa-88e2-4cd9-8e80-2310bff8fc84` passed 10/10 checks:

| Dimension | Passed | What was exercised |
| --- | --- | --- |
| Approval | 2/2 | Unapproved execution blocked; approved execution consumes approval |
| Execution guards | 3/3 | Changed version, changed target, repeated execution |
| Recovery classification | 3/3 | Recovered, not recovered, inconclusive |
| Review workflow | 2/2 | Explicit decline; approved execution linked to matching recovery fixture |

The workflow supplies synthetic review responses and changes only in-memory
state. Recovery uses static measurements matched to the execution's service and
version transition. It does not demonstrate that rollback caused recovery.
The guard checks accept a ValueError with unchanged state rather than checking
each precise rejection reason. This finite suite is not a population safety
violation rate or real incident-resolution success rate.

## Usage, latency, and cost

Replay `735038a9-5f3c-4b2d-acc4-b124d5bd5f36` demonstrates fresh-call telemetry:
Qwen3:8b, seed 42, context 4096, thinking enabled, one diagnosis call with 2,175
input tokens and 863 output tokens. Its diagnosis took about 37.71 seconds.
Historical investigation usage is not included in that replay's totals.

The JSON snapshot includes stage timings for the three saved full runs and the
telemetry example. Their runtimes are observations from different checkpoints,
not a benchmark comparison. Missing token counts remain unknown; they are not
converted to zero. Full-run collection and aggregation have test coverage, but
this snapshot does not supply a live full-run token baseline for all scenarios.

Inference is local through Ollama with no paid inference API. Hardware and
electricity costs are not measured.

## Reproduction and next milestone

With the original local comparison files available, verify review coverage with:

```powershell
python -m evals.review_summary out/comparisons/ee0df895-d512-45d1-8501-e888b4702f6d --comparison
```

The control suite can run from the repository fixtures without historical reports
or Ollama:

```powershell
python -m evals.safety_runner
python -m pytest -q
```

Next is Milestone 9: retrieve runbooks and historical incidents, then measure
whether retrieved evidence improves diagnosis. Keep evaluation expectations out
of agent inputs. Semantic grounding, broader scenarios, and real operational
validation remain open work; retrieval is not assumed to fix them automatically.
