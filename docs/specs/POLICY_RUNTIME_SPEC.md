# Policy Runtime Spec

Nous is an Open Intelligence Runtime.

## Policy Directory

Workspace policies live under `.nous/policies/`.

Supported file extensions:

- `.yaml`
- `.yml`
- `.json`

Policy files may contain either one policy object or a top-level `policies` list.

## Policy Sources

Policy source order is deterministic:

1. system.default
2. runtime.global
3. user
4. workspace
5. project
6. task
7. explicit.override

The effective priority is source order plus policy priority. Higher effective priority wins.

## PolicySpec Fields

Supported fields:

- `policy_id`
- `policy_type`
- `decision_type`
- `version`
- `enabled`
- `priority`
- `conditions`
- `constraints`
- `weights`
- `actions`
- `fallback`
- `metadata`
- `source`
- `schema_version`

Supported first implementation policy types:

- `rule`
- `static`

## Rule DSL

Supported operators:

- `eq`
- `ne`
- `neq`
- `in`
- `not_in`
- `contains`
- `exists`
- `gt`
- `gte`
- `lt`
- `lte`
- `and`
- `or`
- `not`

Fields must start with `task` or `context`. Private attribute paths and dynamic code execution are rejected.

## Hashing

Each policy receives a deterministic `policy_hash` based on its normalized content. Runtime decisions store the hash for the policy that produced the decision.

## Failure Behavior

Invalid ordinary policies are disabled and reported as diagnostics. Runtime startup should continue with safe defaults.

Security-sensitive fail-closed behavior is reserved for the future security policy class; this phase does not implement a permissive fallback for security policy failures.

## CLI

Policy CLI commands:

- `nous policy list`
- `nous policy show <policy-id>`
- `nous policy validate`
- `nous policy validate <path>`
- `nous policy resolve <decision-type>`
- `nous policy explain <policy-id>`
- `nous policy test <policy-id> --input <json>`
- `nous policy diff <old> <new>`
- `nous policy reload`

All commands support `--json`.
