# Milestone 11: persisted workflows

Archived from the root README on 27 October 2026. Commands assume the
repository root as the working directory. Historical next steps, test counts,
and measurements describe their original checkpoints, not current status.

[Archive index](README.md) · [Current milestone status](../milestone-status.md)

---

### Milestone 11: LangGraph foundation

The bounded persistent investigation-and-review checkpoint is complete locally.
See the [Milestone 11 review](../../docs/milestone-11-review.md) for test evidence,
three live scenario checks, remaining reasoning issues, and deferred execution
and recovery work. This is a staged migration: the graph wraps the existing
investigation loop, and approval records a decision without executing rollback.

`app.agent.workflow.build_investigation_graph()` builds an async
`START -> prepare -> investigate -> diagnose -> propose` graph around the existing
agent functions. No-proposal cases end directly; eligible proposals enter a
review node that interrupts for input. It accepts a fixture directory, investigation step limit, diagnosis
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
Approval pauses are tested with an in-memory checkpointer. A user-facing
persistence CLI and graph-based remediation execution are not yet implemented.

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
The initial proposal checkpoint ended both paths; the subsequent review
checkpoint adds the approval interrupt described below.

Tests exercise the existing policy with a scripted supported diagnosis, an
insufficient-evidence diagnosis, and a different target service. They verify
proposal fields and that evidence remains unchanged. Configuration version 2
includes the service and rejects incompatible pending version-1 checkpoints;
service changes are also covered by the resume-guard tests.

Configuration version 4 includes the review stage and correctable review input.
The proposal node creates and
saves a proposal ID before review. The review node requires a checkpointer and
interrupts with that ID, the proposal, diagnosis, and review instructions.
Resuming with `Command(resume="approve <proposal_id>")` or
`Command(resume="decline <proposal_id>")` on the same thread records `approved`
or `declined`, then ends the graph. Approval records a decision only; there is
no rollback execution node. Earlier pending workflow versions are incompatible.

The corrected-review checkpoint passed **20 focused proposal/workflow tests**
and **636 passed, 22 skipped** in the reported full suite. Valid review decisions preserve the
proposal ID and do not repeat investigation or diagnosis. Boolean, blank,
missing-ID, wrong-ID approval/decline, and object responses produce another
interrupt with an error message, without changing the saved proposal or
recording a decision. Tests correct each of these six invalid responses with
explicit approval on the same thread, preserving the proposal ID and evidence
without repeating investigation or diagnosis. Raising after an invalid resume
value previously left that value replaying on retry; the review loop now reaches
a new interrupt for corrected input.

The SQLite review restart checkpoint passed **2 focused tests** and
**638 passed, 22 skipped** in the reported full suite. Each test pauses for
review, closes the first process, and opens the same database and thread in a
second process. Explicit approval and decline preserve the proposal ID,
proposal, investigation, diagnosis, usage, and configuration; only the review
status changes. Investigation, diagnosis, and proposal generation each run
once in the first process and are not repeated after restart. These tests use
scripted investigation and diagnosis with the real proposal builder. They
verify a clean process restart, not a crash during a database write. Execution
after approval is not implemented.

The workflow CLI now supports `python -m app.agent.workflow_cli start` with
required `--database`, `--thread-id`, and `--incident` arguments. Optional
`--scenario`, `--model`, and `--tool-backend` arguments default to
`checkout_regression`, `qwen3:8b`, and `direct`. Diagnosis uses an 8,192-token
context and a 2,048-token generation limit; investigation retains its existing
model configuration. The command prints the saved state, pending nodes, and
review interrupt payloads as JSON.

This checkpoint passed **6 focused CLI tests** and **644 passed, 22 skipped**
in the reported full suite. Tests use scripted model calls with SQLite and
verify that a sequential start with an existing thread ID is rejected without
repeating work. Invalid start arguments are rejected before creating the
database directory. The duplicate-thread check is not a lock against concurrent
starts.

On 26 October 2026, a live direct-backend CLI run for `checkout_regression`
reached the review interrupt, and a separate `inspect` invocation displayed the
saved proposal, configuration, evidence, and usage. Thread
`checkout-b33beb17-2564-4cba-9471-41726dbd2bad` collected metrics, deployment,
commit, and log evidence using five `qwen3:4b` investigation calls and one
`qwen3:8b` diagnosis call. It proposed rollback from `1.7.4` to `1.7.3` and
initially paused as `review_required`. A subsequent live CLI approval and a
separate inspection both showed `approved`, empty pending nodes, and no
outstanding interrupts. Comparing the reported JSON confirmed that only
`proposal_status` changed in the saved state: the proposal ID, evidence,
diagnosis, configuration, and usage remained unchanged. No rollback was
executed. This is an orchestration smoke test,
not an accuracy benchmark: the diagnosis incorrectly described the 0.4 metric
sample as within seven minutes of deployment (13:57 to 14:05 is eight minutes),
and that timing claim cited only metrics rather than also citing deployment
evidence.

A live MCP-backend run for `payment_provider_outage` on 26 October 2026,
thread `provider-mcp-5b2a0e32-ce1f-4de7-811e-a756d7890038`, completed with
`no_proposal`, null proposal and proposal ID, and no pending nodes or interrupts.
The reported start and separate inspection JSON matched exactly. The final
diagnosis cited PayBridge HTTP 503 observations, correctly placed the earliest
observed failure before deployment, and acknowledged that PayBridge's internal
failure cause was unknown. The investigation's earlier narrative incorrectly
framed the error increase as following deployment; this live orchestration check
does not establish that all intermediate reasoning is accurate. No rollback
was proposed or executed.

A live direct-backend `sparse_evidence` run on 26 October 2026, thread
`sparse-df16f62f-d624-490e-9277-a5e1e8ac719e`, returned
`insufficient_evidence`, requested error details and deployment records, and
ended with `no_proposal` and no pending nodes or interrupts. The reported start
and separate inspection JSON matched exactly. The final diagnosis did not
invent a specific failure mechanism. However, the investigation narrative
incorrectly treated an empty deployment result as indicating no recent
deployments and speculated about logging problems from empty log results.
Those intermediate reasoning weaknesses remain unresolved; the successful
abstention and persistence check is not a claim of uniformly accurate reasoning.

Inspect an existing workflow with:

```powershell
python -m app.agent.workflow_cli inspect --database out/workflows/checkpoints.sqlite --thread-id YOUR_THREAD_ID
```

Inspection prints the saved state, pending nodes, and outstanding review
interrupts without invoking workflow nodes or making model calls. The
inspection checkpoint passed **10 focused CLI tests** and **648 passed,
22 skipped** in the reported full suite. Tests cover repeated inspection of
completed workflows and pending reviews, preservation of their state and
interrupt payloads, and rejection of missing databases, unknown threads, and
blank thread IDs. Missing database paths are not created. The SQLite saver
may perform normal database setup; this is not a filesystem read-only
connection.

Resume a pending review using the proposal ID shown by `inspect`:

```powershell
python -m app.agent.workflow_cli resume --database out/workflows/checkpoints.sqlite --thread-id YOUR_THREAD_ID --response "approve YOUR_PROPOSAL_ID"
```

Use `decline YOUR_PROPOSAL_ID` to decline instead. The command reconstructs the
graph from its saved version-4 configuration, including model settings, backend,
service, and scenario path. Approval records a decision only; it does not execute
a rollback. Completed workflows and workflows not waiting for review are rejected.

The review-resume checkpoint passed **11 focused CLI tests** and **649 passed,
22 skipped** in the reported full suite. Tests cover wrong-ID responses remaining
pending, correction with explicit approval or decline, persistence of the decision
when inspected again, and rejection of repeated submission after completion.
Investigation, diagnosis, and proposal generation are patched to fail if repeated
during inspection or review. These tests use scripted model calls and proposals;
they do not establish live diagnosis accuracy or concurrent-review behavior.

Retry a recorded investigation or diagnosis failure with:

```powershell
python -m app.agent.workflow_cli resume --database out/workflows/checkpoints.sqlite --thread-id YOUR_THREAD_ID --retry
```

The retry checkpoint passed **13 focused CLI tests** and **651 passed,
22 skipped** in the reported full suite. Scripted failures verify that retry
uses the saved configuration, repeats the failed node, and persists the completed
result. A diagnosis retry preserves the completed investigation and its recorded
usage. An investigation retry restarts that entire node, so tool calls performed
before failure may repeat. Retry rejects completed workflows and pending reviews;
review still requires an explicit response. The CLI requires a recorded node
error for retry and does not handle abrupt termination without such an error.

