# Milestone 10: MCP

Archived from the root README on 27 October 2026. Commands assume the
repository root as the working directory. Historical next steps, test counts,
and measurements describe their original checkpoints, not current status.

[Archive index](README.md) · [Current milestone status](../milestone-status.md)

---

### Milestone 10: read-only MCP investigation tools

`app.mcp_server.server` uses the MCP Python SDK v2 to expose:

- `search_logs(service, level)`
- `get_deployments(service)`
- `query_metrics(service, metric_name)`
- `get_commit(commit_hash)`

These tools read synthetic fixtures selected at server startup with `--scenario`:
`checkout_regression` (default), `payment_provider_outage`, or `sparse_evidence`.
Tool callers cannot select a scenario or filesystem path. Responses are returned
as structured content under `result`.
Unmatched log, deployment, and metric searches return an empty list; an unknown
commit returns null. No remediation actions are exposed.

The client launches the server with `python -m app.mcp_server.server` and
exchanges MCP messages over stdin/stdout. No listening port, Ollama instance,
or PostgreSQL connection is needed for this checkpoint.

Run the investigation, server, and client checks:

```powershell
python -m pytest tests/test_investigation_executor.py tests/test_mcp_client.py tests/test_mcp_server.py -q
```

`app.mcp_server.client.connect_local_tools(scenario="checkout_regression")`
forwards the scenario to the server and manages one subprocess connection
for multiple calls. Its `MCPToolExecutor.execute()` accepts an existing tool
decision and unwraps the structured response into the direct tool's result
shape. It preserves empty lists and missing commits, rejects unsupported tools,
tool errors, missing result envelopes, and invalid outer result shapes, and
propagates transport failures. It does not validate individual record fields
or automatically retry failed calls.

`investigate_async(..., tool_executor=executor.execute)` can run inside
`async with connect_local_tools() as executor`, using one MCP connection for
the investigation. Tool results retain the existing evidence IDs, observation
messages, and step-record format. Synchronous model selection runs in a worker
thread so it does not block MCP communication. Executor failures propagate.
The synchronous `investigate()` wrapper uses `asyncio.run`; callers already
inside an event loop should await `investigate_async()` instead. `data_dir`
applies only to direct tool execution; MCP uses the scenario configured when
opening the connection.

The reported checkpoint passed **32 focused tests** and **580 tests,
22 skipped** in the full suite. The skipped database checks remain opt-in.
Subprocess tests cover successful and unmatched lookups for all four tools,
malformed log-search arguments followed by a valid call, and a deployment-to-
commit sequence through the adapter on one connection. Stub-client tests cover
adapter failure handling. A scripted-decision investigation test uses the real
MCP subprocess, feeds deployment evidence into the next commit lookup, and
verifies the final investigation record.

The evaluation runner accepts `--tool-backend direct|mcp`, defaulting to
`direct`. MCP supports the three named scenarios using their standard fixture
directories; unknown scenarios and custom fixture directories are rejected.
Each attempt and batch
summary records `tool_backend`. MCP connection startup and shutdown are included
in investigation timing, and connection failures are recorded at that stage.
Diagnosis continues to use the existing model path.

Example live evaluation (requires Ollama):

```powershell
python -m evals.runner --case checkout_regression --runs 1 --tool-backend mcp --model qwen3:8b --num-ctx 8192 --num-predict 2048 --seed 42 --think
```

`--model` selects the diagnosis model; investigation tool selection retains its
existing model configuration. The reported runner checkpoint passed **53 focused tests**
and **593 passed, 22 skipped** in the full suite. Tests cover backend forwarding,
saved backend metadata, unsupported selections, and recorded connection failure.

On 23 October 2026, live checkout-regression run
`51f67ded-4203-405a-b8bf-94f79b137250` in batch
`b0804070-d105-44c9-9d70-9d0470cc38aa` completed with `tool_backend="mcp"`.
It collected metrics, deployments, commit details, and logs in four tool calls,
then stopped by model decision. Required-tool coverage, fixture argument match,
and nonempty-result coverage were all 1.0. Total time was 104.39 seconds
(74.84 investigation, 29.55 diagnosis). Usage recorded five Qwen3 4B
investigation selections and one Qwen3 8B diagnosis call.

This verifies live execution through the MCP backend for one synthetic case,
not a diagnosis accuracy improvement. Inspection found that the diagnosis
identified the relevant deployment and expression but described a missing
`user` attribute rather than `request.user` being `None`. A claim connecting
the exception to the refactor cited only the log, omitting the commit evidence.
Formal diagnosis assessment remains `not_scored`. The full report is stored
locally under `out/evals/` and is not included in this documentation.

The subsequent scenario-support checkpoint passed **18 runner/backend tests**
and **606 passed, 22 skipped** in the full suite. Server subprocess tests compare
all four tools with direct fixture results for each scenario. Scripted model
decisions also exercise the complete runner-to-MCP path for provider outage and
sparse evidence, checking observation messages and diagnosis inputs against the
selected fixtures. Diagnosis generation is stubbed in those tests. Live model
execution over MCP has so far been verified only for checkout regression.

