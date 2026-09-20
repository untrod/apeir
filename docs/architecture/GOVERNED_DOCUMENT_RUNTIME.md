# Governed Document Runtime v1

Status date: 2026-08-31  
Evidence level: native packaged Windows 10 x64 plus integrated-host visual PDF

## Authority

`nous_runtime.documents.service.DocumentRuntime` is the workspace-scoped authority for professional document lifecycle. It extends the existing platform instead of creating parallel state:

- Document IR state: `.nous/documents/doc_<id>.json` with atomic writes and SHA-256 integrity;
- lifecycle history: canonical `EventStream` only;
- generated output identity: canonical workspace `ArtifactRegistry` only;
- mutation authorization: existing API `ExecutionAuthorizationGate` and one-use `ApprovalBroker` lease;
- user experience: Desktop is a control surface over the Runtime API.

## Document IR v1

The schema version is owned by `nous_runtime.schema_registry.DOCUMENT_SCHEMA_VERSION`. A document contains metadata and a bounded ordered block stream. Version 1 supports:

- paragraphs and heading levels 1-3;
- real bullet and numbered lists;
- bounded rectangular tables;
- code blocks;
- citations with safe Source/Snapshot references and plain URL display;
- explicit page breaks.

Limits are enforced before persistence: 500 blocks, 500,000 serialized content characters, 200 list items, 200 table rows, 20 table columns, bounded fields, a strict document identifier, and three resolved style presets. Unknown block types, malformed tables, unsupported versions and embedded NUL content fail closed.

## Render and publish transaction

```text
Document IR
  -> same-directory staging file
  -> DOCX/PDF renderer
  -> parser reopen + safety checks
  -> atomic publish under artifacts/documents
  -> ArtifactRegistry
  -> EventStream
```

An unverified render is removed from staging and never published. A prior verified target is not overwritten until its replacement has passed verification.

DOCX uses explicit Letter geometry, one-inch margins, east-Asian font mapping, Word heading/list styles, fixed DXA table geometry and cell margins, quiet header/footer metadata, and atomic save. PDF uses ReportLab flowables, repeatable table headers, bounded geometry, a Windows CJK font when present, and an atomic output.

## Verification boundary

DOCX verification reopens the OOXML ZIP and requires:

- a valid bounded archive with safe member paths;
- required content, document and style parts;
- no VBA, ActiveX, OLE or embedded object parts;
- no external relationships;
- the Document IR title in document content.

PDF verification requires:

- a valid PDF header and EOF;
- successful strict parser reopen;
- 1-500 pages and no encryption;
- no JavaScript, launch action, embedded file or open action;
- the normalized Document IR title in extracted content.

Both formats are capped at 50 MiB, receive output SHA-256 plus the source IR digest, and are registered only after verification.

## API and governance

Read routes:

- `GET /api/v1/documents/status`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`

Governed mutation routes:

- `POST /api/v1/documents` -> `document.create`, local write, reversible;
- `POST /api/v1/documents/{document_id}/render` -> `document.render`, local write, reversible.

Both capabilities are registered as authenticated, privileged, local Runtime capabilities. The API gate evaluates the full canonical request before the handler runs. Approval produces a one-use lease and the client retries the identical reviewed body.

## Event contract

Create runs emit:

```text
run.created -> command.proposed -> run.started -> document.created
-> artifact.created -> run.completed
```

A successful two-format render emits:

```text
run.created -> command.proposed -> run.started
-> document.rendered -> document.verified -> artifact.created  (DOCX)
-> document.rendered -> document.verified -> artifact.created  (PDF)
-> run.completed
```

Failures emit `document.failed` and `run.failed`; the unverified staging output is removed.

## Desktop

The `Documents` navigation item opens Professional Documents. It provides bounded content composition, three style presets, a persisted library, DOCX/PDF separate or combined export, explicit one-use approval cards, and visible Artifact identifiers, locations, sizes and verification state.

## Honest boundaries

- v1 creates documents from Document IR; importing/editing arbitrary existing DOCX/PDF, tracked changes, comments, forms, images, charts, footnotes and semantic citation formatting remain future increments.
- PDF visual QA passed through Poppler on this host. LibreOffice is not installed, so the DOCX sample passed structural OOXML verification but did not receive LibreOffice page-render certification.
- Rendering runs locally and does not access the network. External relationship and active-content support is intentionally rejected.
- P16 installer install/upgrade/uninstall/reinstall certification remains separate and still requires explicit machine-state authorization.