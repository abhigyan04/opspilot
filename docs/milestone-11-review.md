# Milestone 11 review: persistent LangGraph orchestration

## Scope and outcome

As of 26 October 2026, the bounded investigation-and-review checkpoint is
complete locally. LangGraph coordinates preparation, investigation, diagnosis,
proposal generation, and human review. SQLite preserves state between CLI
processes. Durable review and failure recovery provide a concrete reason for
introducing graph orchestration.

This is a staged migration, not a replacement of every existing control loop.
The investigation node still calls the existing async investigation loop;
individual tool selections are not separate graph nodes. The evaluation runner
and existing remediation simulation remain separate from this graph.

## Implemented behavior

- Direct Python tools and local stdio MCP are supported for synthetic scenarios.
- Investigation and diagnosis record separate usage snapshots.
- Version-4 configuration records the fixture path, backend, model settings,
  step limit, and service. Resume reconstructs that configuration, and work
  nodes reject mismatches.
- The existing proposal policy produces either no proposal or a rollback
  candidate with a persisted proposal ID.
- Review pauses before a decision. Explicit approval or decline must name the
  saved proposal ID. Invalid responses produce a correctable interrupt.
- Approval records a decision and ends the graph. It does not execute rollback.
- CLI commands start, inspect, review, and retry recorded investigation or
  diagnosis failures. Completed workflows cannot be resumed through the CLI.

## Verification

The latest user-reported suite result is **651 passed, 22 skipped**, including
**13 CLI tests**. The skipped PostgreSQL checks are opt-in; this result does not
claim they were executed. No new test run was needed for this documentation-only
review.

Tests exercise thread isolation, configuration mismatch rejection, SQLite
reopening, and resume in separate processes. Review restart tests cover both
approval and decline while preserving proposal identity and avoiding repeated
investigation, diagnosis, or proposal generation. CLI tests cover start,
inspection, invalid-response correction, review persistence, and retry routing.
These tests use scripted model calls; some CLI tests also stub proposal policy.

Three live local-model smoke tests were reviewed from user-pasted CLI output:

| Scenario | Backend | Final outcome | Persistence check |
| --- | --- | --- | --- |
| Checkout regression | direct | Rollback candidate approved for review purposes only | Resume and subsequent inspection matched; only proposal status changed from the pending state |
| Payment-provider outage | mcp | Supported diagnosis, no proposal | Start and separate inspection JSON matched exactly |
| Sparse evidence | direct | Insufficient evidence, no proposal | Start and separate inspection JSON matched exactly |

Thread IDs:

- Checkout: `checkout-b33beb17-2564-4cba-9471-41726dbd2bad`
- Provider: `provider-mcp-5b2a0e32-ce1f-4de7-811e-a756d7890038`
- Sparse: `sparse-df16f62f-d624-490e-9277-a5e1e8ac719e`

The local database is `out/workflows/checkpoints.sqlite`. Neither that database
nor the pasted transcripts are bundled with this review. JSON comparisons were
performed against the supplied transcripts, not a fresh query of the database.
These are single-run smoke checks, not an accuracy benchmark or verification
of remote CI results.

## Known limitations

- Checkout diagnosis incorrectly described an eight-minute interval as seven
  minutes and cited metrics alone for a deployment-relative timing claim.
- Provider investigation reasoning initially placed the increase after the
  deployment, although the final diagnosis correctly placed failures before it.
- Sparse investigation reasoning inferred no deployments from an empty result
  and speculated about logging faults. The final diagnosis correctly abstained.
- Retrying investigation restarts its entire node and can repeat earlier tool
  calls. Usage from a failed node is not preserved in its completed-node snapshot.
- Process tests cover clean shutdown and reopening, not crashes during writes.
  CLI retry requires a recorded error and does not cover abrupt termination
  without one.
- Sequential duplicate-start checks are not concurrency locks. Concurrent
  review submissions and multiple workers are not verified.
- Configuration checks do not fingerprint fixture contents, model weights,
  or application code. Schema versioning is not a migration mechanism.
- Inspection does not advance the graph, but the saver may perform database
  setup; the connection is not filesystem read-only.
- No rollback execution, durable action idempotency, or recovery verification
  node is integrated. There is no production infrastructure connection.

## Next scope

The next milestone can expose this bounded workflow through a local API and UI:
start an investigation, inspect evidence and status, and submit an explicit
review decision. Its initial scope should preserve the existing decision-only
approval behavior. Authentication, concurrent mutation controls, background
execution, and deployment need explicit design before expanding beyond a local
single-user prototype.

Connecting approved proposals to execution and recovery is a separate extension.
It requires current-state revalidation and durable duplicate-action protection;
an `approved` state alone must not be treated as proof an action ran successfully.
