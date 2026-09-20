# Workspace Runtime Specification v1.0

> Status: Draft — Phase 0.5
> Workspace isolation, leases, quotas, cleanup

---

## 1. Workspace Types

### 1.1 CloudWorkspace
Runs on a cloud worker node. Ephemeral. Used for CI-like tasks, code review, testing.

### 1.2 PersonalWorkspace
Runs on a personal laptop node. Persistent (user-managed). Used for development tasks requiring personal files or tools.

---

## 2. Workspace Identity

```json
{
  "identity_id": "wsid_20260713_a1b2",
  "workspace_id": "ws_20260713_c3d4",
  "role": "personal_node",
  "owner": "proj_20260713_a1b2",
  "git_remote": "https://github.com/user/repo.git",
  "git_ref": "main",
  "created_at": "2026-07-13T10:00:00Z"
}
```

---

## 3. Workspace Lease

### 3.1 Schema
```json
{
  "lease_id": "lease_20260713_e5f6",
  "workspace_id": "ws_20260713_c3d4",
  "holder": "wi_20260713_m3n4",
  "acquired_at": "2026-07-13T10:00:00Z",
  "expires_at": "2026-07-14T10:00:00Z",
  "renewable": true,
  "exclusive": true
}
```

### 3.2 Rules
- **Exclusive**: Only one lease per workspace at a time
- **Renewable**: Long-running tasks can renew lease
- **Expiry**: Expired lease -> workspace eligible for cleanup
- **Release**: Task completion/failure -> lease released immediately

---

## 4. GitWorktreePolicy

```yaml
policy:
  require_clean_worktree: true     # Base must be clean before branching
  require_branch: true             # Must create a branch (no detached HEAD)
  branch_naming: "nous/{work_item_id[:12]}"  # Predictable branch names
  auto_prune_after: 86400          # Prune worktree 24h after task completion
  reject_detached_head: true       # Deny detached HEAD
  reject_dirty_base: true          # Deny if base has uncommitted changes
```

### 4.1 Worktree Setup
```
1. git worktree add --detach {workspace_path} {base_branch}
2. cd {workspace_path}
3. git checkout -b nous/{work_item_id[:12]}
4. Verify: branch is clean, not detached, not dirty
```

---

## 5. Workspace Quota

```json
{
  "quota": {
    "max_size_bytes": 1073741824,
    "max_files": 100000,
    "max_age_seconds": 86400,
    "max_concurrent_workspaces": 5
  }
}
```

### 5.1 Enforcement
- Size checked on file write (reject if would exceed)
- File count checked on file create
- Age checked by cleanup daemon (background)
- Concurrent workspace limit enforced at workspace creation

---

## 6. Workspace Cleanup Policy

```json
{
  "policy": {
    "on_completion": "remove",
    "on_failure": "keep_for_3600_then_remove",
    "on_expiry": "remove",
    "artifact_retention": "keep_artifacts",
    "remove_workspace": true,
    "remove_checkout": true
  }
}
```

### 6.1 Cleanup Actions
- `remove`: Delete workspace directory and git worktree
- `keep_for_N_then_remove`: Keep for N seconds (debugging), then remove
- `keep_artifacts`: Move artifacts to artifact store before removing workspace

### 6.2 Cleanup Invariants
- Never delete the canonical git repository
- Never delete uncommitted work without artifact save
- Never delete artifacts marked for retention
- Cleanup runs as background daemon, not inline with task execution

---

## 7. Workspace Snapshot

```json
{
  "snapshot_id": "snap_20260713_g7h8",
  "workspace_id": "ws_20260713_c3d4",
  "taken_at": "2026-07-13T14:00:00Z",
  "git_commit": "abc123def456",
  "file_list": [
    {"path": "src/daemon.py", "hash": "sha256:...", "size": 2048}
  ],
  "diff_from_base": "diff --git a/...",
  "secret_scan_result": "clean"
}
```

---

## 8. WorkspaceArtifact

```json
{
  "artifact_id": "art_20260713_i9j0",
  "workspace_id": "ws_20260713_c3d4",
  "work_item_id": "wi_20260713_m3n4",
  "path": "diffs/daemon.patch",
  "hash": "sha256:abc123...",
  "type": "diff",
  "secret_free": true,
  "created_at": "2026-07-13T14:00:00Z"
}
```

### 8.1 Artifact Export Rules
1. Scan for secrets before export (reject if found)
2. Validate path (no traversal, within workspace)
3. Bound size (max 100 MB per artifact)
4. Hash for integrity verification
5. Record in project artifact registry

---

## 9. Path Security

### 9.1 Allowed Paths
- Explicit glob patterns in `workspace.allowed_paths`
- Default: `["{workspace_root}/**"]` — only within workspace
- Can be further restricted per WorkItem

### 9.2 Path Validation
```python
def validate_path(requested_path, workspace_root, allowed_patterns):
    # Resolve to absolute
    absolute = os.path.realpath(requested_path)
    
    # Must be within workspace root
    if not absolute.startswith(os.path.realpath(workspace_root)):
        raise PathTraversalError(f"Path {requested_path} is outside workspace")
    
    # Must match an allowed pattern
    if not any(fnmatch(absolute, p) for p in allowed_patterns):
        raise PathNotAllowedError(f"Path {requested_path} not in allowed paths")
    
    return absolute
```

### 9.3 Rejected Patterns
- `..` path segments
- Absolute paths (unless within workspace after resolution)
- Symlinks to locations outside workspace
- Hidden files (`.env`, `.git`, etc.) — read-only unless explicitly allowed
- Device files, named pipes, sockets

---

## 10. Cross-Workspace Synchronization

### 10.1 Methods
1. **Git**: push from source workspace, pull in target workspace
2. **Signed artifacts**: hash-verified artifact transfer via Control Plane

### 10.2 Prohibition
Cloud and laptop workspaces must NEVER directly share a filesystem. No NFS, no SMB, no network mounts.
