# Milestone 10 review: MCP

## Scope and outcome

The project handoff defines this milestone as exposing operational integrations
through MCP after understanding direct Python integration. The bounded local,
synthetic implementation meets that scope. It does not establish production
integration readiness or improved diagnosis accuracy.

## Implementation

- A local stdio MCP server wraps the existing `search_logs`, `query_metrics`,
  `get_deployments`, and `get_commit` functions.
- Startup configuration selects checkout regression, provider outage, or sparse
  evidence. Tool arguments do not accept scenario names or filesystem paths.
- A client adapter manages one subprocess connection across multiple calls,
  unwraps structured results, rejects tool errors and invalid outer result
  shapes, and propagates transport failures.
- The async investigation loop accepts the adapter while retaining the same
  evidence IDs, observation messages, and report steps. Synchronous callers
  retain direct execution by default.
- The evaluation runner exposes `--tool-backend direct|mcp` and records the
  choice in attempts and batch summaries. It rejects unsupported scenarios and
  custom fixture directories for MCP.
- Remediation actions remain outside the MCP server.

## Verification

The user-reported final local checkpoint was **606 passed, 22 skipped**, with
**18 runner/backend tests** passing separately. Database tests remain opt-in.

Subprocess tests verify tool discovery, input schemas, matching and unmatched
lookups, scenario-specific result parity, and a valid call after malformed
log-search arguments. Adapter tests cover malformed responses, tool errors,
transport failures, and rejection of unsupported tools.

Scripted-decision tests exercise the investigation loop over MCP. The provider
outage and sparse-evidence tests exercise the full runner-to-server path and
verify that the selected fixture evidence reaches observations and diagnosis
input. Model calls are stubbed in these tests.

One live checkout-regression run completed on 23 October 2026:

- Batch: `b0804070-d105-44c9-9d70-9d0470cc38aa`
- Run: `51f67ded-4203-405a-b8bf-94f79b137250`
- Backend: `mcp`
- Four tool calls, followed by a model finish decision
- Required-tool coverage, fixture argument match, and nonempty-result coverage: 1.0
- Total duration: 104.39 seconds
- Five Qwen3 4B investigation selections and one Qwen3 8B diagnosis call

The report was inspected locally under `out/evals/`; it is not bundled here.
Its diagnosis identified the relevant change but confused a missing `user`
attribute with `request.user` being `None`, and one refactor-related claim cited
only the log. Formal diagnosis assessment remains `not_scored`.

## Limits and follow-up

This is local stdio access to synthetic fixtures, not a connection to production
logs, metrics, deployments, or Git. There is no HTTP deployment or remote
authentication configuration. The adapter validates outer result shapes, not
individual record fields. Live model runs for provider outage and sparse
evidence have not been verified through MCP.

The existing GitHub Actions workflow runs the full pytest suite on Ubuntu with
Python 3.12. Its latest hosted result was not verified during this closeout.

The handoff makes Milestone 11 (LangGraph) conditional on workflow complexity.
The next step is to assess the current state transitions and identify a concrete
need, such as persistence and resuming human approval, before choosing a graph
migration scope.
