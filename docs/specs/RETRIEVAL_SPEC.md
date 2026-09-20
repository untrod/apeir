# Retrieval Fabric Specification

Nous is an Open Intelligence Runtime.

Retrieval Fabric is the read-only discovery layer for runtime memory, tasks,
plans, observations, artifacts, devices, and future document or code indexes.
It does not replace authoritative stores. It derives searchable records from
canonical runtime data and can be rebuilt without changing source state.

## Responsibilities

- Define a canonical `RetrievalRecord` that every backend can index.
- Define tenant and project scope checks before records are returned.
- Define `RetrievalQuery`, `RetrievalFilters`, and `RetrievalResult` for CLI,
  Shell, API, device clients, and future UI surfaces.
- Define a backend protocol so local, embedded, and external retrieval engines
  share one contract.
- Preserve traceable links back to source records through `source_id`,
  `source_type`, `stable_key`, and `supersedes`.

## Non-Responsibilities

- Retrieval Fabric does not mutate Memory, TaskGraph, Plan, Observation, or
  Device state.
- Retrieval Fabric does not decide task execution.
- Retrieval Fabric does not make vector storage authoritative.
- Retrieval Fabric does not require a network service in the baseline.
- Retrieval Fabric does not expose backend-specific SDK calls outside backend
  implementations.

## Canonical Record

`RetrievalRecord` contains:

- `record_id`: stable retrieval-layer identifier.
- `record_type`: one of the supported retrieval record types.
- `workspace_id` and `project_id`: isolation boundary.
- `source_id` and `source_type`: pointer to the authoritative source.
- `title` and `content`: searchable text.
- `content_hash`: hash of the derived content.
- `stable_key`: optional logical identity, used by facts and stable entities.
- `version` and `supersedes`: lifecycle metadata.
- `created_at` and `updated_at`: source timeline.
- `metadata`: backend-neutral JSON metadata.
- `access_scope`: workspace, project, principal, and visibility guard.
- `embedding_status` and `index_status`: derived indexing state.

Baseline supported record types:

- `memory_event`
- `memory_fact`
- `memory_decision`
- `memory_summary`
- `memory_experience`
- `memory_artifact`
- `task`
- `plan`
- `observation`
- `artifact`
- `document_chunk`
- `code_symbol`
- `device_record`

## Query Model

`RetrievalQuery` contains `text`, `scope`, `filters`, `limit`, `mode`, and an
optional trace flag. The baseline supports lexical and exact behavior in the
local reference backend. Dense, sparse, hybrid, and structured modes are
reserved by the model and must be implemented behind the backend protocol.

`RetrievalFilters` covers record type, source type, task, capability, provider,
metadata equality, time window, and active-only selection.

`RetrievalResult` contains the source record, normalized score, rank, matched
text, backend name, and an explanation payload suitable for external tools.

## Backend Protocol

Backends implement:

- `manifest()`
- `ensure_index(spec)`
- `upsert(records)`
- `delete(record_ids, scope)`
- `search(request)`
- `health()`
- `verify(spec)`

Backends publish a manifest describing support for dense, sparse, lexical,
filtering, write, delete, and multi-tenant behavior. Backend-specific clients
remain inside backend modules.

Production backends also implement the storage contract:

- `list_record_ids(generation_id, scope)`
- `count(generation_id, scope)`
- `clear_generation(generation_id)`
- `generation_exists(generation_id)`

Generation-aware storage is required for production verification.

## Index Generations

Retrieval indexes are managed through explicit generations. A generation moves
through the following states:

- `building`
- `shadow`
- `active`
- `draining`
- `retired`
- `failed`

Only a verified `shadow` generation can become `active`. The manager drains and
retires older active generations during activation. Generation state is stored
by Nous, not only inside a backend.

The local metadata store writes:

- `.nous/retrieval/index_generations.jsonl`
- `.nous/retrieval/index_events.jsonl`

The first rebuild pipeline is synchronous and supports batch writes. The API is
structured so future outbox workers can run the same generation lifecycle
asynchronously.

## Export And Rebuild

`RetrievalRecordExporter` exports canonical records from authoritative stores.
The baseline exporter covers structured project Memory. It supports full export
and preserves the cursor model for incremental export.

`RetrievalIndexManager` owns:

- generation creation
- canonical export
- backend batch writes
- consistency verification
- activation
- retirement
- status reporting

Verification checks expected count, actual count, missing records, orphan
records, duplicate record IDs, and content hash mismatches for backends that
expose records.

## Embeddings

Embedding providers are registered through `EmbeddingRegistry` and described by
`EmbeddingModelManifest`. The baseline includes a deterministic local hash
embedding provider for tests and development. It is not a production semantic
embedding model.

Production embedding models must publish dimension, vector fields, distance
metric, provider ID, and metadata before they are used by a durable backend.
`FastEmbedEmbeddingProvider` is available as an optional, lazy-loaded local
provider. It does not download or initialize a model until embedding is
explicitly requested. Providers should support batch document embedding, query
embedding, manifest validation, lexical fallback when unavailable, and no
logging of full text or vectors.

## Outbox Jobs

Indexing jobs use a JSONL outbox. The baseline supports enqueue, lease,
complete, fail, and list operations. Jobs are not automatically run by the
Runtime yet; this avoids background behavior that would surprise operators.

## Hybrid Retrieval And Ranking

The baseline includes a hybrid orchestration layer and ranking helpers. It can
combine lexical and dense result sets when both are available. Context packing
turns ranked retrieval results into a bounded text block with dropped-record
tracking.

## Evaluation

Retrieval evaluation uses explicit cases with expected record IDs. This gives a
stable entry point for later recall, precision, and regression suites.
The production report includes Recall@1, Recall@5, MRR, nDCG@5, and latency
p50/p95. Evaluation sets should include Chinese technical documents, mixed
Chinese-English queries, exact ID lookup, fuzzy semantic lookup, superseded
exclusion, and cross-project isolation.

## TaskGraph Integration

TaskGraph integration is explicit. `TaskGraphRetrievalBridge` can build a
retrieval context for a task, but it is not automatically injected into planning
or execution. This keeps retrieval observable and avoids hidden prompt changes.
Supported injection modes are `disabled`, `explicit`, and `policy`. The default
remains explicit. Future automatic policy mode must emit a
`RetrievalContextDecision` containing the reason, query ID, and selected record
IDs.

## Local Reference Backend

The baseline includes an in-memory local backend for deterministic contract
tests and development. It supports lexical scoring, filters, scope isolation,
upsert, delete, health, and index verification metadata. It is not durable and
is not intended to be the production retrieval store.

## Persistent Local Backend

The production local data plane uses SQLite at:

- `.nous/retrieval/local_index.sqlite3`

It stores indexed records by generation and supports cross-process verification.
Required tables:

- `retrieval_records`
- `generation_records`
- `backend_metadata`

Required indexes cover workspace/project scope, generation, record type, stable
key, and active status.

## Qdrant Data Plane

The Qdrant adapter is optional and remains dependency-free until explicitly
configured. It defines `QdrantCollectionSpec` with collection name, generation,
dense vector name, sparse vector name, dimension, distance metric, payload
indexes, sharding policy, replication factor, and on-disk storage.

Payload fields include `record_id`, `generation_id`, `workspace_id`,
`project_id`, `record_type`, `source_type`, `stable_key`, `active`,
`content_hash`, `created_at`, and `metadata`.

Collection names are sanitized and include a hash suffix to keep names stable
and bounded. Dense upsert and filtered dense search are available when a Qdrant
client and embedding provider are supplied.

## Scope And Access

Every search request has a `RetrievalScope`. A backend must reject records whose
workspace or project does not match the query scope. Principal filtering applies
when records contain principal-level access metadata. External backends must
apply equivalent checks before returning results.

## Memory Mapping

Structured Memory remains authoritative. The Memory mapper creates derived
retrieval records from Memory events, facts, decisions, summaries, experiences,
and artifact references. The mapper preserves source identifiers and
supersession links so a newer fact can hide the old fact by default while still
allowing historical queries when `active_only` is disabled.

## Lifecycle

1. Authoritative runtime data is created or updated.
2. A derived `RetrievalRecord` is generated.
3. A backend upserts or removes derived records.
4. Search returns scoped `RetrievalResult` objects.
5. Authoritative data remains the source of truth.

Derived indexes can be deleted and rebuilt from authoritative data.

## Failure Semantics

Retrieval errors must not crash the Runtime. Backends report health and
verification details through typed result objects. Callers should treat
retrieval as best-effort context unless a command explicitly requires it.

## Telemetry

Search results may include explanations and backend details. Future metrics
should track query count, latency, backend health, stale records, missing
records, and scope rejections without recording private content.

## Security Boundary

Retrieval output is scoped by workspace and project. Derived indexes must not
broaden access beyond the source record. External backends must keep backend
configuration out of code and documentation. Sensitive values must be redacted
before records are indexed.

## Planned Extensions

The following remain outside the default runtime path:

- production embedding provider integration tests
- production Qdrant deployment configuration and integration tests
- sparse retrieval backend
- automatic indexing workers
- automatic TaskGraph context injection policy
- visualization UI
