# Milestone 12: API, container, and simulation checks

Archived from the root README on 27 October 2026. Commands assume the
repository root as the working directory. Historical next steps, test counts,
and measurements describe their original checkpoints, not current status.

[Archive index](README.md) · [Current milestone status](../milestone-status.md)

---

### Milestone 12: local API foundation

The bounded local UI and Docker deployment checkpoint is reviewed in
[Milestone 12 review](../../docs/milestone-12-review.md), including verification
evidence, known limitations, and deferred production scope.

Follow the [milestone 12 demo procedure](../../docs/milestone-12-demo.md) to replay
the local deployment and review flow. Its baseline commit is linked to a
verified passing CI run.

Install the project dependencies, then start the FastAPI application locally:

```powershell
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, check the endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`GET /health` returns `{"status": "ok"}`. It confirms the API responds, not
that Ollama, PostgreSQL, or workflow execution is ready. Interactive endpoint
documentation is available at `http://127.0.0.1:8000/docs`.

On 26 October 2026, the user verified successful server startup, HTTP 200 from
`/health`, and the expected response. `pip check` reported no broken
requirements; the reported suite remained **651 passed, 22 skipped**. This is
a manual health smoke check.

`GET /workflows/{thread_id}` now returns saved state, pending nodes, and review
interrupts without advancing the workflow. The server selects the database
(by default `out/workflows/checkpoints.sqlite` under the project root); callers
cannot select a database through request parameters. Unknown threads return
404, a missing database returns 503, and blank thread IDs return 422.

The inspection checkpoint passed **17 combined API/CLI tests** and
**655 passed, 22 skipped** in the reported full suite. Automated tests cover
health without a database, missing databases, unknown and blank thread IDs,
and repeated inspection of completed and review-pending workflows. Model and
proposal calls are stubbed during setup and fail if called during inspection;
persisted state is checked afterward.

On 26 October 2026, a live HTTP inspection of the saved checkout thread returned
`approved` with the original proposal ID and empty pending nodes and interrupts.
Comparison with the earlier CLI transcript confirmed matching proposal,
diagnosis, configuration, usage, and tool-result evidence. Two investigation
decision-reason strings differed only in spacing between words in the pasted
transcripts, so exact whole-response equality was not established. The API
omits the CLI's top-level database path. An HTTP retry endpoint and deployment
are not implemented yet.

The start-request schema is defined in `app/api/schemas.py`. It accepts an
incident string of 1–4,000 characters containing non-whitespace text, one of
the three supported scenarios, and a `direct` or `mcp` tool backend. Defaults
are `checkout_regression` and `direct`. Incident formatting is preserved;
unknown fields and invalid types are rejected. Database, thread ID, model,
and review responses are not client-selectable fields in this request.
The character limit is not a model token-budget guarantee.

This schema checkpoint passed **19 focused tests** and **674 passed,
22 skipped** in the reported full suite.

`POST /workflows` now accepts that schema and calls the existing workflow start
function with a server-generated UUID thread ID and `qwen3:8b` diagnosis model.
The request waits for completion or a review pause, then returns HTTP 201 with
saved state and a `Location` header pointing to the inspection endpoint. This
is not background execution; repeating a POST creates a new workflow.
Invalid requests return 422 before work starts. Execution exceptions are logged
and return 500 with a generic message and the generated thread ID, without raw
exception details. Failure before checkpoint creation may leave no saved thread
to inspect.

The POST contract checkpoint passed **31 combined API/schema tests** and
**682 passed, 22 skipped** in the reported full suite. New tests verify request
forwarding, distinct generated IDs, inspection links, validation before work,
and error responses. They stub the start function.

The subsequent persistence checkpoint passed **14 combined persistence/API
tests** and **684 passed, 22 skipped** in the reported full suite. Tests use
the real workflow start function, graph, SQLite saver, and proposal policy with
scripted investigation and diagnosis. Both a completed no-proposal workflow
and a review-pending workflow are retrieved through their POST `Location`
links by a new application instance. Repeated GET responses match the POST
state without rerunning investigation, diagnosis, or proposal generation.
This verifies reopening in the same process, not an HTTP server process restart.
On 26 October 2026, a live HTTP POST for `checkout_regression` created thread
`workflow-33e51b50-5761-4ced-bff8-5f8194f3dcea` and paused for review with proposal
`e44d2bcb-d640-4c54-ba6b-2291bb6560b9` (`1.7.4` to `1.7.3`). The supplied POST
and subsequent GET JSON matched exactly, including evidence and usage. The
proposal remains pending; no rollback was executed. The investigation narrative
incorrectly interpreted `rollback_target_version` as evidence of an already
completed rollback. The final diagnosis repeated the previously noted
seven-versus-eight-minute timing error. These are known reasoning defects;
the HTTP creation and persistence check does not establish diagnosis accuracy.

The review-request schema requires `proposal_id` and an explicit `approve` or
`decline` decision, with no default decision. IDs must be nonempty strings of
at most 128 characters without whitespace. Extra fields are rejected, so a
review request cannot modify the proposed target version. This validates the
request shape only; matching the ID to the pending proposal is the endpoint's
responsibility.

The review-schema checkpoint passed **33 focused schema tests** and
**698 passed, 22 skipped** in the reported full suite.

`POST /workflows/{thread_id}/review` now checks that the workflow is paused for
review and the submitted proposal ID matches before forwarding the explicit
decision to the existing resume function. Approval records a decision only;
it does not execute rollback. Unknown threads return 404, missing databases
return 503, and stale IDs or completed/non-review workflows return 409.
Invalid request bodies return 422 before lookup.

The review contract checkpoint passed **20 combined review/API tests** and
**706 passed, 22 skipped** in the reported full suite. These tests stub lookup
and resume; they verify decision forwarding, sequential repeat rejection,
conflict rejection without resume, lookup errors, and request validation.
An application-local lock serializes HTTP review
handling within one app instance; it does not coordinate CLI processes or
multiple server workers.

The subsequent review persistence checkpoint passed **11 combined
persistence/review tests** and **707 passed, 22 skipped** in the reported full
suite. It uses the real graph, proposal policy, resume function, and SQLite
with scripted investigation and diagnosis. Approval and decline persist across
new app instances; only the proposal status changes in saved state. Stale IDs,
no-proposal workflows, duplicate decisions, and attempts to reverse a completed
decision are rejected without changing the checkpoint. Earlier workflow work
must not repeat. These persistence checks use sequential requests in one process.

The subsequent concurrency checkpoint passed **10 focused review tests** and
**709 passed, 22 skipped** in the reported full suite. Controlled overlapping
HTTP requests exercise both approve-then-decline and decline-then-approve. The
first request succeeds; the second reads the updated state and returns 409
without calling resume. These tests exercise the actual routes and app-local
lock with stubbed inspection and resume, not concurrent SQLite transactions.
Coordination across app instances, server workers, or CLI processes remains
outside this guarantee.

On 26 October 2026, after restarting Uvicorn, live HTTP review of thread
`workflow-33e51b50-5761-4ced-bff8-5f8194f3dcea` returned HTTP 200 and recorded
`approved` for proposal `e44d2bcb-d640-4c54-ba6b-2291bb6560b9`. A subsequent
GET also returned HTTP 200. The supplied response JSON matched exactly between
review and GET; comparison with the earlier pending state found only
`proposal_status` changed. Proposal identity, evidence, diagnosis, configuration,
and usage remained unchanged, with empty pending nodes and interrupts. No
rollback was executed. This completes one live HTTP start, inspect, review,
and inspect sequence; it is not a concurrency or diagnosis-accuracy benchmark.

The initial browser viewer is served at `http://127.0.0.1:8000/` from
`app/web/index.html`. It loads an existing workflow by thread ID and displays
its incident, diagnosis and citations, limitations or missing evidence,
proposal, review status, and expandable tool-result evidence. The start form
accepts an incident, synthetic scenario, and direct Python or local MCP backend.
It waits for the POST response and displays the created workflow ID and result.
Browser review controls allow approval or decline of a displayed pending
proposal. Approval records a decision only; it does not execute a rollback.
Dynamic content is rendered with `textContent`.

After adding the viewer, the reported suite remained **709 passed, 22 skipped**.
This suite result does not verify browser behavior. Separately, user-reported
browser output on 26 October 2026 confirmed the saved approval label, diagnosis
and citations, and visible expanded evidence. Loading `unknown-workflow`
displayed `Workflow not found.` with the previous incident, diagnosis, proposal,
and evidence no longer displayed. These are manual checks, not automated browser
coverage.

After adding the start form, the reported suite remained **709 passed, 22 skipped**.
User-reported browser output on 26 October 2026 showed creation of
`workflow-cef6d6df-d686-4034-a32c-e96b3fecbfc2`, an insufficient-evidence diagnosis,
missing logs and deployment history, and no proposed action. This confirms the
displayed start result; it does not establish a diagnosis-accuracy improvement.
The user also confirmed that both forms were disabled during the request and
loading this new workflow by ID displayed the same result. These are manual
browser checks, not automated browser coverage.

After adding browser review controls, the reported suite remained **709 passed,
22 skipped**. User-reported browser output showed
`workflow-7cc24558-6d87-46fa-beee-7f91cdbe93bb` loaded with status `Declined` and
no review buttons displayed, confirming the saved decline remained visible on
reload. A subsequent browser approval for
`workflow-fd79dbd5-9fd0-4fa2-8eb2-47ee82ce6daa` displayed the review-saved message,
`Approved · not executed`, and no review buttons. The user then reloaded this
workflow and confirmed the same approved status with no review buttons.
These manual checks do not demonstrate
rollback execution or improved diagnosis accuracy.

The user also confirmed a two-tab stale-review check for
`workflow-1ff55f8a-f27c-4ad4-8c24-131c1810859c`: after declining in the first tab,
an approval attempt from the stale second tab displayed the expected
`Workflow is not waiting for review.` error and reload instruction. Loading
the workflow again showed `Declined` with no review buttons. This manual
check confirms the later stale submission did not overwrite the saved decision;
it is not a simultaneous-request or multi-process concurrency test.

### Local application container

Build and start the single-worker application with Docker Compose:

```powershell
docker compose config --quiet
docker compose up -d --build --wait app
docker compose ps app
Invoke-RestMethod http://127.0.0.1:8001/health
```

Open `http://127.0.0.1:8001/`. The application runs as a non-root user and
connects to Windows-hosted Ollama through
`OLLAMA_HOST=http://host.docker.internal:11434`. Investigation uses `qwen3:4b`
and diagnosis uses `qwen3:8b`; both must be available in that Ollama instance.
The health check tests API liveness only, not model connectivity.

The `workflow_data` named volume stores SQLite checkpoints at
`/opt/opspilot/out/workflows/checkpoints.sqlite`. This is separate from the
Windows checkout's `out/workflows` directory. The image includes application
code, the browser page, and synthetic scenario fixtures; its build-context
allowlist excludes local environment files and saved reports. This deployment
does not configure the RAG knowledge corpus or retrieval database connection.

User-reported checks confirmed the image imports, non-root execution, log-tool
fixture access, writable checkpoint storage, dependency consistency, healthy
API, browser page, and container-to-Ollama model listing. A direct-backend
checkout investigation created
`workflow-d6525bf1-0a47-4cbc-9d9e-f4b3a8d60672`. Following the container-recreation
procedure, the user reported loading its pending proposal, declining it, and
loading the persisted `Declined` state after another recreation, with no review
buttons displayed.

```powershell
docker compose up -d --force-recreate --wait app
```

The user subsequently reported a Local MCP payment-provider-outage run,
`workflow-ccddc3bd-72d4-45f3-ac3d-117b213fccc2`, created through the container
UI. Its displayed evidence listed `query_metrics`, `get_deployments`,
`get_commit`, and `search_logs`. The diagnosis identified PayBridge HTTP 503
responses, noted that the earliest observed error preceded the deployment,
and left the provider's internal cause unresolved. No action was proposed.
This is a user-reported MCP deployment smoke check; the pasted view did not
include expanded tool payloads or saved backend configuration.

These are manual local deployment checks, not automated container tests,
crash-recovery tests, or diagnosis-accuracy improvements. No rollback was
executed. Keep the
named volume when recreating the service; `docker compose down -v` removes
Compose-managed named volumes, including saved checkpoints and PostgreSQL data.

The GitHub Actions workflow also includes a separate `Docker smoke test` job.
It builds the image, starts its normal server command, checks the health JSON
and HTML delivery, exercises the log fixture tool, and checks non-root execution
and writable checkpoint storage. It requires neither Ollama nor PostgreSQL.
The user reported that both `Python tests` and `Docker smoke test` passed in
the remote Actions run. Subsequent verification through GitHub's public API
confirmed [run 40343931610](https://github.com/abhigyan04/opspilot/actions/runs/40343931610)
and both jobs succeeded for commit `0cf4afda767b73f4328af42792e81b62f921f8a6`.
This automated smoke test does not execute browser JavaScript, run model
inference, or verify named-volume persistence; those remain separate checks.

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

