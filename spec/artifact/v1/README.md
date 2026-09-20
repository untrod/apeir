# Nous Content Artifact v1

R3 artifacts are immutable, SHA-256 content-addressed objects. The durable index
records their type, media type, size, provenance label and graph relationships.
Resolving or fetching an artifact verifies its bytes; an index entry never
substitutes for content verification.

Pins protect an artifact and its transitive `depends_on` / `derived_from` graph.
Garbage collection is a dry run unless the caller explicitly requests mutation.
State-changing store, pin, unpin and applied-GC operations emit operation
receipts.
