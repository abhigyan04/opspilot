# Milestone 12 review: local UI and Docker deployment

## Scope and outcome

The bounded local, single-user UI and deployment checkpoint is complete based
on the implemented code and user-reported verification. FastAPI exposes the
persistent investigation-and-review workflow, a browser interface supports its
main operations, and Docker Compose runs the application with durable SQLite
storage. Models remain on the Windows host through Ollama.

The handoff's potential stack is not a requirement to introduce every listed
technology. This implementation uses plain HTML and JavaScript rather than
React or Next.js. Cloud deployment remains deferred under the local-only scope.
This checkpoint does not establish production readiness or improved diagnosis
accuracy.

## Implemented behavior

- Start a synthetic-scenario investigation using Direct Python or Local MCP.
- Load saved workflow state, diagnosis, citations, limitations, and tool evidence.
- Approve or decline a pending proposal by its persisted proposal ID.
- Reject stale reviews and require reloading after an uncertain review result.
- Preserve workflow state and review decisions in SQLite across container replacement.
- Run one application worker as a non-root container user, exposed on
  `127.0.0.1:8001`, with a separate named checkpoint volume.
- Run Python tests and a Docker build/startup smoke check in GitHub Actions.

Approval records a review decision only. Neither the API nor this workflow
executes a rollback. The browser renders dynamic content using `textContent`.
The API selects storage and model configuration; clients do not supply a
database path or model through the start request.

## Verification and evidence

The latest supplied local suite result was **709 passed, 22 skipped**. The
PostgreSQL integration checks are opt-in and were not executed in that result.
API tests cover request validation, inspection, review conflicts, persistence
across application instances, and controlled concurrent review requests within
one application instance. These tests use scripted or stubbed model calls.

User-reported browser checks covered start, busy controls, saved-ID loading,
unknown-ID handling, approval, decline, and persistence of both decisions on
reload. The two-tab check declined a proposal first, then rejected a stale
approval and reloaded the saved decline. That was sequential stale-state
handling, not a simultaneous-request or multi-process test.

Representative reported workflows:

| Workflow ID | Check and reported result |
| --- | --- |
| `workflow-cef6d6df-d686-4034-a32c-e96b3fecbfc2` | Browser start, insufficient evidence, no action, reload confirmed |
| `workflow-7cc24558-6d87-46fa-beee-7f91cdbe93bb` | Browser decline persisted on reload |
| `workflow-fd79dbd5-9fd0-4fa2-8eb2-47ee82ce6daa` | Browser approval persisted as approved, not executed |
| `workflow-1ff55f8a-f27c-4ad4-8c24-131c1810859c` | Stale approval rejected after decline in another tab |
| `workflow-d6525bf1-0a47-4cbc-9d9e-f4b3a8d60672` | Docker Direct Python investigation; pending state and subsequent decline reloaded after reported container recreations |
| `workflow-ccddc3bd-72d4-45f3-ac3d-117b213fccc2` | Reported Docker Local MCP provider-outage run; four tool headings, PayBridge 503 diagnosis, no action |

The Docker image checks confirmed imports, UI and fixture presence, log-tool
execution, non-root execution, writable checkpoint storage, and dependency
consistency. Compose checks confirmed API health, page delivery, volume writes,
and container access to both required Ollama models. The MCP browser transcript
did not include expanded tool payloads or saved backend configuration.

The user reported both remote CI jobs passing. The Docker job builds and starts
the image, asserts health JSON and HTML delivery, exercises a fixture tool,
and checks user identity and filesystem writes. It does not run browser
JavaScript, model inference, or named-volume persistence checks. No remote run
URL or commit SHA was supplied, so this review records the reported result
without attributing it to an independently verified revision.

Workflow databases and pasted transcripts are not bundled with this document.
The browser and container outcomes above are based on supplied output and user
confirmations, not a fresh inspection of the saved databases.

## Operational boundaries and remaining limitations

- The service is intended for local single-user use. Authentication,
  authorization, TLS, and public deployment are not implemented.
- Review serialization uses an application-local lock. It does not coordinate
  multiple workers, replicas, or concurrent CLI mutations.
- Start requests wait for execution. There is no background job queue, durable
  start-request idempotency, or browser cancellation/reconnection protocol.
  A lost response can leave the caller uncertain about a created workflow.
- The API does not expose the CLI's failed-node retry operation.
- `/health` is liveness only. Logs are basic; dependency readiness, operational
  metrics, tracing, and alerting remain future work.
- Named-volume checks cover orderly container recreation, not abrupt crashes,
  backup restoration, or storage corruption. Deleting the volume deletes its
  checkpoints. Windows-local and container checkpoint stores are separate.
- The image does not configure RAG knowledge data or a retrieval database
  connection. PostgreSQL remains a separate existing retrieval service.
- Dependencies and the base-image tag are not fully pinned for reproducible
  builds. A later build can resolve different versions.
- Browser behavior has manual coverage; the Docker CI HTML checks do not
  substitute for automated browser interaction tests.
- The recurring checkout diagnosis describes an eight-minute deployment-to-
  metric interval as seven minutes and cites metrics alone for that relative
  timing claim. Successful deployment and review do not resolve this known
  grounding issue.
- Execution, current-state revalidation, durable duplicate-action protection,
  and recovery verification are separate extensions. An approved state must
  never be interpreted as successful execution.

## Next scope

Keep the application within its local decision-only boundary. A useful next
checkpoint is a reproducible demo and evidence package tied to a commit and CI
run, including the known limitations above. Further feature work should have
an explicit objective, such as diagnosis grounding, automated browser tests,
or background execution, rather than adding technologies solely to match the
handoff's potential stack.
