# Milestone 12: reproducible local demo

This demo exercises synthetic incident investigation, evidence inspection,
human review, and persistent workflow state. It uses local Ollama models and
Docker Desktop on Windows. It does not connect to production systems or execute
rollback actions.

## Revision and verification record

- Implementation/review baseline: [`0cf4afda767b73f4328af42792e81b62f921f8a6`](https://github.com/abhigyan04/opspilot/commit/0cf4afda767b73f4328af42792e81b62f921f8a6).
- Passing CI run for this exact revision: [40343931610](https://github.com/abhigyan04/opspilot/actions/runs/40343931610).
- GitHub API verification: run completed successfully with head SHA
  `0cf4afda767b73f4328af42792e81b62f921f8a6`; both `Python tests` and
  `Docker smoke test` completed successfully.
- Earlier reported local result: 709 passed, 22 skipped. This is historical
  evidence, not a new test result for this document.

The baseline was read from the local repository and matched to the remote run
through GitHub's public API. The
documentation commit containing this procedure will be a later revision; it
does not retroactively associate earlier manual runs with the baseline SHA.

## Prerequisites

- Docker Desktop running Linux containers with Docker Compose available.
- Ollama running on the Windows host, with `qwen3:4b` and `qwen3:8b` installed.
- Port 8001 available on localhost.
- Enough memory to run the models. The demonstrated machine has 16 GB RAM and
  an RTX 4070 Laptop GPU with 8 GB VRAM; latency on other machines may differ.

Use a separate checkout to replay the baseline without changing ongoing work:

```powershell
git clone https://github.com/abhigyan04/opspilot.git opspilot-m12-demo
Set-Location opspilot-m12-demo
git checkout --detach 0cf4afda767b73f4328af42792e81b62f921f8a6
git rev-parse HEAD
git status --short
docker version
docker compose version
ollama --version
ollama list
```

If necessary, install the two models with `ollama pull qwen3:4b` and
`ollama pull qwen3:8b`. Model downloads require network access and disk space.
The build also downloads its base image and Python dependencies.

## Start and check connectivity

```powershell
docker compose config --quiet
docker compose up -d --build --wait app
docker compose ps app
Invoke-RestMethod http://127.0.0.1:8001/health
docker compose exec -T app python -c "from ollama import Client; print(Client(timeout=10).list())"
```

Expect a healthy application, `status: ok`, and both required models in the
listing. The health endpoint alone does not establish model connectivity.
Compose directs the Ollama client to `http://host.docker.internal:11434`.
PostgreSQL is not required for this workflow demo.

## Main demonstration

1. Open `http://127.0.0.1:8001/`.
2. Enter `Errors in checkout-service have increased significantly. Investigate.`
3. Select **Checkout regression** and **Direct Python**, then start.
4. Keep the page open until it returns a workflow ID. Record that ID.
5. Inspect the diagnosis, citations, and expanded evidence. In the observed
   runs, this scenario produces a rollback candidate awaiting review.
6. Leave the proposal pending and recreate the container:

   ```powershell
   docker compose up -d --force-recreate --wait app
   ```

7. Refresh the page and load the recorded ID. Check that the pending proposal,
   diagnosis, and evidence remain available.
8. Decline the proposal. Check that the status is `Declined` and review buttons
   disappear.
9. Recreate the container again, refresh, and reload the same ID. Confirm the
   decline persists.

Do not treat a different diagnosis, missing proposal, or failed request as a
successful demo of the review path. Preserve the workflow ID and inspect its
evidence or logs rather than retrying until a favorable result appears.

## Optional MCP contrast

Start another investigation with the same incident text, **Payment-provider
outage**, and **Local MCP**. Record the new ID and expand tool evidence.
The demonstrated outcome identifies PayBridge 503 responses, notes errors
before the checkout deployment, leaves the provider's internal cause unknown,
and proposes no action. These are review criteria, not guaranteed model output.

For insufficient-evidence behavior, select **Sparse evidence**. Empty logs and
deployment results should lead to uncertainty rather than an invented cause.
Neither optional case requires approving or executing a remediation.

## Capture and limitations

Record the checked-out SHA, CI run URL and head SHA, Docker/Ollama versions,
model IDs from `ollama list`, workflow IDs, and observed outcomes. Useful demo
captures are expanded evidence, the pending proposal after recreation, and the
persisted decline. Saved workflow IDs are local to their checkpoint volume and
are not public links.

This is a repeatable procedure, not a bit-for-bit reproducible build or model
benchmark. Dependencies and model tags can change; generation can vary. The
known checkout timing/citation defect remains documented in the
[milestone review](milestone-12-review.md). CI verifies tests and container
startup, not these live model outcomes or browser interactions.

The named volume stores checkpoints separately from a Windows Python run.
Do not use `docker compose down -v` to stop the demo: it deletes Compose-managed
volumes. Stop the application while retaining its data with:

```powershell
docker compose stop app
```

If a request fails, record its returned ID and inspect the saved workflow before
resubmitting. Collect application logs with:

```powershell
docker compose logs --tail 100 app
```

Public hosting, authentication, a polished portfolio UI, and a recorded/public
demo are subsequent portfolio-release work, outside this local closeout.
