# Milestone 9: retrieval and diagnosis references

Archived from the root README on 27 October 2026. Commands assume the
repository root as the working directory. Historical next steps, test counts,
and measurements describe their original checkpoints, not current status.

[Archive index](README.md) · [Current milestone status](../milestone-status.md)

---

### Milestone 9: local knowledge collection

The [knowledge catalog](../../data/knowledge/catalog.json) lists two synthetic
runbooks and one fictional historical incident. Their Markdown files live under
`data/knowledge/`, separately from evaluation fixtures in `data/scenarios/`.
The documents provide operational guidance without copying scenario-specific
commits, versions, timestamps, or expected diagnoses. Historical observations
are reference material, not evidence about a current incident.

[`load_documents`](../../app/retrieval/documents.py) validates catalog metadata and
loads UTF-8 Markdown into immutable document records. Each record retains its
stable document ID, type, title, relative source path, synthetic flag, text,
and SHA-256 hash of the exact file bytes. The loader rejects duplicate IDs or
resolved paths, blank titles or contents, unsupported document types, and
invalid paths. Resolved document paths must remain inside the knowledge root.
Missing files and decoding errors propagate rather than silently omitting data.

[`chunk_document`](../../app/retrieval/chunks.py) splits the current prose documents
at Markdown `##` headings. It retains opening text as an introduction, keeps
subheadings within their section, and skips empty sections. Each immutable
passage carries document metadata, its section, the source-file hash, and an ID
formed from the document ID, source hash, and passage position. Editing any part
of a document changes all its passage IDs; the IDs identify document versions,
not permanent anchors across revisions.

The three current documents produce 14 nonempty passages (5, 5, and 4), with
passage bodies ranging from 113 to 589 characters. The splitter has no length
limit and is not a general Markdown parser: heading-like lines inside fenced
code need handling before such documents are added. A splitter algorithm change
also requires index invalidation; document hashes alone do not version that code.

Retrieved passages must remain labeled as reference material, including when
the introduction disclaimer is not retrieved.

### Local embeddings

[`embeddings.py`](../../app/retrieval/embeddings.py) uses `embeddinggemma:300m` through
Ollama at `http://localhost:11434`, with 768-dimensional vectors and input
format version 1. Queries use `task: search result | query: ...`; passages use
`title: DOCUMENT TITLE — SECTION | text: ...`. Formatting is separate from
the original passage contents used for citations.

Prepare the local model:

```powershell
ollama pull embeddinggemma:300m
```

Ollama must be running for live embedding calls. Open the Ollama application or
run `ollama serve` in a separate terminal. The adapter rejects blank inputs,
incorrect vector counts or dimensions, nonfinite values, and zero vectors.
It requests `truncate=False`, makes no server call for empty batches, and lets
server errors propagate. Tests use fake clients and require no running server.

The user-reported suite passed 368 tests. The live smoke check then embedded all
3 documents' 14 passages and one query successfully, producing 14 passage
vectors and a query vector with 768 dimensions. This establishes that the
formatted embedding path works; it does not establish retrieval relevance.

Local JSON index persistence and pgvector storage are implemented below.
Optional diagnosis augmentation is implemented in replay. Index manifests identify the embedding
model digest, format version, and source contents.
The development retrieval evaluation below precedes agent integration.

### Passage ranking

[`rank_chunks`](../../app/retrieval/search.py) normalizes query and passage vectors,
ranks by descending cosine similarity, and uses chunk IDs to break equal-score
ties deterministically. Hits retain the full passage metadata for later citation.
The ranker validates vector values and dimensions, chunk/vector counts, unique
chunk IDs, and positive integer `top_k`. It does not call Ollama.

The user-reported suite passed 386 tests. A live exploratory search over the
14 passages returned the following results with `top_k=3`:

| Query topic | Highest-ranked passage | Score | Other observations |
| --- | --- | --- | --- |
| Upstream HTTP 503 | Dependency errors / Symptoms | 0.5733 | Investigation ranked second; all three hits came from the dependency runbook. |
| AttributeError involving None | Application exceptions / Symptoms | 0.5631 | Investigation ranked second; all three hits came from the exception runbook. |
| Inventory reservation timeouts | Inventory incident / Historical observations | 0.7063 | All three hits came from the historical incident. |
| Chocolate cake | Application exceptions / Investigation | 0.1299 | All returned passages were unrelated to the query. |

These four queries are a smoke check, not a retrieval benchmark or diagnosis
accuracy result. Similarity is not a relevance probability. The ranker always
returns up to `top_k` hits when passages are available, even for unrelated
queries; no relevance threshold or abstention policy is calibrated yet. The
symptom matches rank above investigation guidance in the two runbook examples,
so document-level matching alone is insufficient to measure useful retrieval.

### Retrieval development evaluation

```powershell
python -m evals.retrieval_runner --top-k 3
```

The runner embeds the collection once, evaluates eight queries, and saves a
report under `out/retrieval/` (`--output-dir` overrides the destination).
Expectations in `evals/retrieval_cases.py` identify document/section pairs and
are used only for scoring, not supplied to the retriever. Six positive cases
include paraphrases; two negative cases cover cooking and unsupported production
database details. This small authored development set is not held-out evidence
of generalization.

Report `ef6a523e-7ed4-4bb8-a2cc-1978248f3e96` completed with `top_k=3`:

| Measure | Result |
| --- | --- |
| Positive queries with an expected section in top 3 | 6/6 (hit rate 1.0) |
| Mean expected-section recall at 3 | 1.0 |
| Mean reciprocal rank at 3 | 0.8333 |
| Negative queries returning passages | 2/2 |

The first relevant section ranked second for `dependency_investigation` and
`exception_investigation`, and first for the other four positive cases. Both
expected inventory sections appeared in its top three. Negative cases are
excluded from positive-case averages; their highest scores were 0.1408 for
cooking and 0.3911 for unsupported database details. The latter demonstrates
that topical similarity does not establish answerability. No relevance cutoff
has been calibrated, and the report does not measure diagnosis improvement.

Reports retain per-query ranks and judgments, passage text and metadata, source
hashes, code hashes, model tag, format version, and elapsed time. The installed
model digest is not yet recorded by this evaluation runner (the index preparation
path below does record it). `completed` means the evaluation ran, not
that retrieval met a quality threshold. Errors propagate without saving an
incomplete report as completed. The user-reported suite passed 407 tests;
runner tests use fake embeddings and do not require Ollama.

### Local index preparation and reuse

[`prepare_index`](../../app/retrieval/prepare.py) loads the current collection, creates
passages, and obtains the exact configured model tag's digest from local Ollama.
The manifest includes model identity, dimensions, embedding format version,
chunking version, and complete ordered passage records. Its deterministic
fingerprint names the JSON index file inside the caller's chosen directory.
Changes to these inputs select a different file rather than overwriting an old
index. Increment the chunking or formatting version when those algorithms change.

```python
from pathlib import Path
from app.retrieval.prepare import prepare_index

index = prepare_index(Path("out/indexes"))
print(index.path, index.reused, len(index.chunks))
```

A matching index loads vectors without embedding the passages again. Ollama
must still be running: preparation checks model identity before and after the
operation. An observed identity change prevents a newly built index from being
saved. This detects changes across the operation but does not lock the model
registry. The retrieval entry point below adds a check after query embedding.

The index loader checks payload integrity, the expected manifest, vector counts,
dimensions, finite numeric values, and nonzero vectors. Corrupt files raise an
error rather than triggering silent replacement. Hashes detect accidental edits,
not malicious modification with recomputed hashes. Exclusive file creation
prevents overwrites; writes are not atomic, and an interrupted write can leave
an invalid file that must be handled explicitly.

The user-reported suite passed 450 tests. The live smoke check built and then
reused 14 passage vectors of 768 dimensions under
`out/indexes/85e42b4b-ac69-4cb5-af3c-167ea0f9abc3/` with manifest fingerprint
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695`.
The model digest was
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
The saved file's integrity and vector shape were checked separately without
calling Ollama. Generated indexes remain local under ignored `out/`.

### Search a saved index

[`retrieve`](../../app/retrieval/retrieve.py) validates the query and `top_k`, prepares
or reuses the matching passage index, embeds the query, and checks model identity
again before ranking. Observed identity changes raise an error instead of
returning results that may mix incompatible vectors. These before/after checks
do not lock the model registry against concurrent updates.

```python
from pathlib import Path
from app.retrieval.retrieve import retrieve

result = retrieve(
    "What should I investigate when a dependency returns HTTP 503?",
    Path("out/indexes"),
    top_k=3,
)
print(result.index_reused)
for hit in result.hits:
    print(hit.chunk.document_id, hit.chunk.section, hit.score)
```

Repeated searches in the same directory reuse passage vectors while generating
a fresh query vector. The result includes index path, reuse status, embedding
identity, and ranked hits with citation metadata. Ollama is still required for
identity checks and query embedding.

The user-reported suite passed 458 tests. A live search reused the index under
`out/indexes/85e42b4b-ac69-4cb5-af3c-167ea0f9abc3/` for the development query about
upstream 503 errors and deployment reasoning. Dependency-runbook sections ranked
Symptoms (0.5055), Investigation (0.4806), and Response considerations (0.3859),
matching the earlier evaluation's order and scores to four decimal places.
This validates the reuse path for one query, not general retrieval quality or
diagnosis improvement. No relevance cutoff or abstention policy is applied.

### Local PostgreSQL and pgvector

[`docker-compose.yml`](../../docker-compose.yml) runs PostgreSQL 17 with pgvector
0.8.7 using `pgvector/pgvector:0.8.7-pg17-bookworm`. The published port is
`127.0.0.1:5433`, mapped to container port 5432. The database and user are
`opspilot`; `opspilot_local_dev` is the explicit local development password.
This setup uses the image's bootstrap database user, not a production
least-privilege application role.

```powershell
docker compose config --quiet
docker compose up -d --wait postgres
docker compose ps
docker compose exec -T postgres psql -U opspilot -d opspilot -v ON_ERROR_STOP=1 -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

The named `postgres_data` volume persists database files across container
recreation. [`001_enable_vector.sql`](../../infra/postgres/init/001_enable_vector.sql)
enables the extension during first initialization. Initialization scripts run
only for a new database volume; adding later SQL files does not automatically
apply them to an existing database. Subsequent schema changes must be applied
explicitly.

The user verified a healthy container, extension version `0.8.7`, and cosine
distance 0 for two identical vectors. These checks establish database and
extension availability. Retrieval tables and schema integration tests are now
implemented below, together with passage import and SQL ranking. The high-level
`retrieve()` function still uses the JSON index.

Stop the service while preserving data with:

```powershell
docker compose stop postgres
```

`docker compose down -v` removes the database volume and its data; it is not
needed for normal startup, shutdown, or schema updates.

### Retrieval schema and database tests

Apply [`001_retrieval_tables.sql`](../../infra/postgres/migrations/001_retrieval_tables.sql)
once to an initialized database:

```powershell
Get-Content -Raw infra/postgres/migrations/001_retrieval_tables.sql |
    docker compose exec -T postgres psql -U opspilot -d opspilot -v ON_ERROR_STOP=1 -f -
```

The migration creates `retrieval.indexes` for manifests and expected passage
counts, and `retrieval.passages` for metadata and `vector(768)` embeddings.
Passages reference an index fingerprint; chunk IDs and positions are unique
within each index. Constraints reject invalid metadata, zero vectors, and
missing parent indexes. Pgvector enforces vector dimensions and finite values.
The migration runs in a transaction and intentionally fails if its tables
already exist. There is not yet an automated migration-history mechanism.

Python connects through the `psycopg[binary]` project dependency. The user
verified connectivity to `opspilot`, extension version 0.8.7, and both tables.
The schema does not itself prove that a manifest matches its fingerprint or
passages, or that all expected passages exist. The importer validates its input
file against the caller's expected manifest and inserts all rows atomically;
SQL search also checks stored metadata and passage counts.

Database tests require an explicit connection string:

```powershell
$env:OPSPILOT_TEST_DATABASE_URL = "postgresql://opspilot:opspilot_local_dev@127.0.0.1:5433/opspilot"
python -m pytest tests/test_pg_schema.py -q
python -m pytest -q
Remove-Item Env:OPSPILOT_TEST_DATABASE_URL
```

Use the local development database for these tests. Each test rolls back its
temporary records, including on failure. Without the variable, database tests
skip; with it set, connection errors fail rather than skip. The verified
user-reported results were 458 passed / 10 skipped without configuration,
10 passed for the schema tests alone, and 468 passed for the configured full
suite. Existing CI does not configure this database, so those integration tests
remain skipped there.

### PostgreSQL import and search

[`pg_store.py`](../../app/retrieval/pg_store.py) provides `import_index()` and
`search_index()`. Both require an expected manifest supplied by the caller.
Import validates the saved JSON index, requires 768-dimensional vectors, and
inserts the manifest and ordered passages in one transaction. An insertion
failure rolls back the entire import; duplicate index fingerprints raise an
error rather than overwriting existing data. Within an existing transaction,
the importer uses a savepoint and leaves the outer commit to its caller.

SQL search scopes results to the manifest fingerprint, checks stored manifest
metadata and passage count, validates the query vector, and verifies returned
passage metadata against the expected records. It ranks by cosine similarity
(`1 - cosine distance`) with chunk-ID ties sorted using the `C` collation.
No approximate vector index or relevance cutoff is used. These checks do not
revalidate every stored vector's provenance or lock against concurrent database
edits. The caller still owns query-model compatibility checks.

The live import reused the local index with fingerprint
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695` and stored all
14 expected passages. A subsequent shared-query-vector smoke check found the
same three dependency-runbook passages as Python, in the same order, with scores
matching within `rel_tol=1e-5, abs_tol=1e-6`. Pgvector stores single-precision
values, so small differences are expected. This was one-query parity validation,
not a full database-backed retrieval evaluation.

The user-reported importer/search integration suite passed 12 tests and the full
database-enabled suite passed 480 tests. Tests cover atomic rollback, duplicate
imports, stale manifests, ranking, missing/incomplete indexes, changed returned
content, tie order, and invalid query vectors. All test records are rolled back.

### PostgreSQL retrieval orchestration and development parity

[`retrieve_postgres`](../../app/retrieval/pg_retrieve.py) builds the expected manifest
from current documents, passages, and the installed embedding model identity.
It embeds only the query, rechecks model identity, and calls SQL search for the
matching imported index. It does not import data or generate passage embeddings
during a search. Missing indexes and observed model changes raise errors. The
caller supplies and owns the database connection; the function does not commit
or close it. As with JSON-backed retrieval, identity checks do not lock Ollama's
model registry against concurrent changes.

The user-reported normal suite passed 466 tests with 22 database tests skipped
after adding this entry point. Its eight orchestration unit tests use fake
backends; the live checks below separately exercise PostgreSQL and Ollama.

Saved development report `out/retrieval/8508ffc5-edff-4bfa-9b48-a7cf46a4dbf7.json`
evaluated all eight queries through PostgreSQL against index
`001659867233cd610c9b1efea24272c117a545cd8b756b4612fdf9db3d90c695`:

| Measure | PostgreSQL result |
| --- | --- |
| Positive queries with an expected section in top 3 | 6/6 |
| Mean expected-section recall at 3 | 1.0 |
| Mean reciprocal rank at 3 | 0.8333 |
| Negative queries returning passages | 2/2 |

Comparison with Python report `ef6a523e-7ed4-4bb8-a2cc-1978248f3e96` verified
identical queries, expected sections, ordered top-three chunk IDs, and relevance
judgments for every case. All 24 scores matched within `rel_tol=1e-5,
abs_tol=1e-6`; the largest absolute difference was approximately `9.79e-8`.
This establishes parity on this small development set, not new relevance gains,
held-out generalization, or diagnosis improvement. Both negative queries still
return passages because no abstention filter is applied.

The PostgreSQL report was produced by a one-off evaluation script and records
the model identity and index fingerprint, but not the full code hashes captured
by the existing Python runner. A reusable database evaluation CLI is not yet
implemented. Generated reports remain local artifacts under `out/`.

### Optional references in diagnosis

[`build_reference_context`](../../app/retrieval/context.py) converts ordered search
hits into reference records with full passage text, source metadata, and
`reference:<chunk_id>` identifiers. It rejects duplicate chunk IDs and blank
content. Similarity scores are excluded from diagnosis input because retrieval
similarity is not diagnostic confidence.

[`generate_diagnosis`](../../app/agent/agent.py) accepts an optional `reference_hits`
argument. Nonempty references are supplied separately from operational
observations. The prompt treats them as untrusted background guidance for
hypotheses, not current-incident evidence or instructions to execute.

Operational citation IDs remain the only IDs allowed in `evidence_ids`, and
runtime validation rejects reference IDs used as evidence citations. With no
operational steps, diagnosis still returns `insufficient_evidence` without a
model call, even when references are available.

Both diagnosis statuses now support a separate `reference_notes` list for
background guidance. Each note contains a statement of up to 600 characters and
one to three `reference_ids`; at most three notes are allowed. Older diagnoses
without this field default to an empty list, which appears in newly serialized
output. Root cause and supporting claims still require operational `evidence_ids`.

The generation schema restricts reference citations to supplied passage IDs.
Without references it permits zero notes. Runtime validation independently
rejects unknown reference IDs, including operational evidence IDs used in notes,
for both supported and insufficient-evidence diagnoses. The prompt directs
runbook guidance into reference notes rather than operational claims. These
checks establish citation membership and separation, not whether a cited source
actually supports the statement.

The reference-note integration checkpoint passed **548 tests, 22 skipped** in
the user-reported full suite. Live provider-outage replay
`8dc79d7b-f131-4fdd-843c-853446eed920` (under the comparison directory's
`reference-notes/` folder) used identical investigation data, reference context,
and model settings to bounded replay `830a0606-6fe9-4585-9110-e34b56d081b0`.
It returned three operational supporting claims and two separate reference notes.
The notes cited the dependency runbook's Symptoms and Investigation passages;
the prior misuse of the logging diff to cite runbook guidance was absent.
It retained correct metric values, failure-before-deployment ordering, and an
explicit unknown provider cause, without importing the inventory incident's cause.

This is a single-case citation-separation improvement after changing both schema
and prompt, not an aggregate accuracy result or proof of RAG's benefit over a
matched no-reference baseline. The Symptoms note paraphrased the source more
strongly than its conditional wording, and the note text redundantly included
long citation IDs. The run reported 1,207 output tokens and 47.98 seconds for
diagnosis, below the configured 2,048-token generation cap.

The reported checkpoint passed 34 focused diagnosis tests and the full suite
with **475 passed, 22 skipped**. The skipped checks require the opt-in database
test URL. Tests cover reference serialization, separate payloads, citation
validation, and the no-observations guard. They do not establish model resistance
to instructions embedded in references or improved diagnosis accuracy.

Reference input currently has no token budget or relevance-abstention filter.
Controlled comparisons remain necessary before claiming diagnosis improvement.

### Replay with PostgreSQL references

The replay CLI supports opt-in retrieval using query version 2 from
[`build_retrieval_query`](../../app/retrieval/query.py). It searches with up to three
distinct ERROR/CRITICAL log messages in observation order, normalizing whitespace
and limiting each message to 300 characters. When a record omits its level, the
requested log level is used. Without usable messages, it falls back to normalized
incident text limited to 400 characters, without an added label. These are query
character limits, not a diagnosis token budget. Previous model reasoning,
diagnoses, and expected answers are not used as retrieval queries.
The database must already contain the index matching the current knowledge
collection and embedding identity; replay does not import or rebuild it.

```powershell
docker compose up -d --wait postgres
$env:OPSPILOT_DATABASE_URL = "postgresql://opspilot:opspilot_local_dev@127.0.0.1:5433/opspilot"
python -m evals.replay <saved-report.json> --model qwen3:8b --seed 42 --num-ctx 4096 --think --with-references --retrieval-top-k 3
Remove-Item Env:OPSPILOT_DATABASE_URL
```

Replace `<saved-report.json>` with a version 2 investigation report. Ollama must
be running with the diagnosis and embedding models available. The URL shown is
for the local development Compose service. This command reads the process
environment, not an `.env` file. `OPSPILOT_TEST_DATABASE_URL` remains the separate
opt-in setting for database tests.

Without `--with-references`, replay does not connect to PostgreSQL.
`--retrieval-top-k` controls passage count; `--top-k` controls model sampling.
The CLI owns and closes the connection. A connection failure exits with code 1
before creating a report. Retrieval and diagnosis failures inside replay are
saved with their respective error stages.

Saved reports include the supplied `reference_context` separately from the
unchanged investigation. PostgreSQL runs also record the retrieval query,
query version and strategy,
requested passage count, index ID, embedding identity, ordered chunk IDs and
scores, and retrieval duration. Scores are not passed to diagnosis. Reference
context is retained on diagnosis failure; its presence records supplied input,
not proof that the model used it. CLI output is a compact summary; inspect the
saved report for the reference context and retrieval metadata.

The reported CLI checkpoint passed **37 replay tests**, with **486 passed,
22 skipped** in the full suite. These tests mock database and model calls;
they verify orchestration and reporting, not diagnosis accuracy.

The subsequent query-version-2 checkpoint passed **50 focused query/replay
tests**, with **499 passed, 22 skipped** in the full suite. Database checks remain
opt-in. Retrieval-only development comparisons on checkout regression and
provider outage used the same index and embedding identity. Error-only queries
ranked the respective runbook's Symptoms section first and Investigation second.
With incident-plus-error queries, inventory history ranked first; checkout's
application Investigation section was absent from the top three, and dependency
Investigation ranked third for provider outage. Less relevant historical material
still appeared at rank three with error-only queries.

This is a retrieval improvement on two known development cases, not held-out
generalization or demonstrated diagnosis improvement. Query version 2 has not
established an overall diagnosis accuracy gain. No relevance-abstention policy is
implemented, and sparse evidence can still retrieve unrelated references.

### Bounded diagnosis generation

Diagnosis generation now supplies a positive `num_predict` limit, defaulting to
2,048 tokens. Both `evals.replay` and `evals.runner` accept `--num-predict`; the
effective value is recorded in diagnosis settings. This controls diagnosis
generation only, not investigation tool-selection calls. It is not a wall-clock
timeout or a guarantee that the input and output fit within `num_ctx`.

A response with `done_reason="length"` raises `DiagnosisGenerationLimitError`
before JSON parsing, even if its content could be parsed. Usage is collected
first. Replay saves the attempt as a diagnosis-stage failure with no accepted
diagnosis, retaining the investigation and available token counts. It does not
automatically retry.

The diagnosis schema also limits supporting claims to six, limitations to four,
missing-evidence items to six, and citation IDs per claim to twelve. Claim text,
limitations, the insufficient-evidence reason, and missing-evidence items are
limited to 600 characters each. Runtime validation rejects duplicate statements
across the root cause and supporting claims after case and whitespace
normalization. This does not detect paraphrases or verify factual support.
Oversized historical diagnoses may therefore fail validation under the current
schema; saved artifacts are not rewritten.

The reported checkpoint passed **54 focused generation-limit/replay tests** and
**527 passed, 22 skipped** in the full suite. Offline tests verify option
forwarding, schema bounds, duplicate rejection, and a saved limit-termination
failure with usage preserved and no retry. These controls bound accepted output
and request generation limits; they do not establish improved diagnosis accuracy.

A subsequent live provider-outage replay (`830a0606-6fe9-4585-9110-e34b56d081b0`,
under `out/comparisons/40359ea0-b6fa-47a6-aa13-f3b4cb71084a/bounded-ctx8192/`)
completed with Qwen3 8B, an 8,192-token context, and a 2,048-token generation cap.
It reported 899 output tokens, six supporting claims, four limitations, and
43.76 seconds for diagnosis. The user reported 100% GPU placement at that context.
This run avoided the previous repetition loop, but did not hit the token cap,
so live limit-termination handling remains untested. Schema and generation limits
changed together; their individual effects cannot be isolated from this run.
The diagnosis still cited the logging diff for a general dependency-pattern
claim, so semantic citation support remains unresolved.
