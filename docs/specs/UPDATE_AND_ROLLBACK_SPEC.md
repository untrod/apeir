# Update and Rollback Specification v1.0

> Status: Draft — Phase 0.5 — Design only, NOT IMPLEMENTED
> Release channels, promotion rules, rollback

---

## 1. Release Channels

| Channel | Source Branch | Configuration | Data | Port | Credentials | Update Authority | Promotion |
|---|---|---|---|---|---|---|---|
| **stable** | `main` or `release/*` | `config.stable.json` | `data/stable/` | 8770 | Production | Human | N/A (target) |
| **candidate** | `candidate/*` | `config.candidate.json` | `data/candidate/` | 8771 | Candidate | Automated (after human approval) | Health check pass + approval -> stable |
| **development** | `nous/dev/*` | `config.dev.json` | `data/dev/` | 8772 | Development | Developer | All gates pass -> candidate |

---

## 2. Channel Isolation

| Aspect | Isolation Mechanism |
|---|---|
| Source code | Git branches or separate checkouts |
| Configuration | Separate config files |
| Data (SQLite, JSONL) | Separate data directories |
| Network port | Port offset (+1 for candidate, +2 for dev) |
| Credentials | Separate API keys and node credentials |
| Process | Separate OS processes |

---

## 3. Promotion Flow

```
Development ──(all gates)──► Candidate ──(health + approval)──► Stable
                                │
                                └──(health fail)──► ROLLBACK
```

### 3.1 Development -> Candidate
**Gates**:
- [ ] All tests pass
- [ ] Ruff lint passes
- [ ] Security scan passes (no HIGH findings)
- [ ] Compileall passes
- [ ] Clean-install smoke passes

### 3.2 Candidate -> Stable
**Gates**:
- [ ] All health checks pass (Step 12)
- [ ] Human approval (Step 9)
- [ ] Approval evidence persisted
- [ ] Rollback plan verified

---

## 4. Rollback

### 4.1 Automatic Rollback Triggers
- Candidate fails to start
- Any health check fails
- Performance regression beyond threshold (configurable)
- Error rate increase beyond threshold

### 4.2 Manual Rollback
- `nous server rollback` — revert to previous stable
- Requires explicit confirmation
- Rollback record persisted

### 4.3 Rollback Process
1. Stop candidate instance
2. Restore previous stable configuration
3. Start previous stable instance
4. Verify health
5. Record rollback decision
6. Clean candidate data directory

### 4.4 Rollback Limitations
- Database migrations: must be backward-compatible (no destructive changes in migrations)
- Configuration changes: must be backward-compatible (new config keys ignored by old version)
- API changes: must follow deprecation policy (2 minor versions before removal)

---

## 5. Release Artifact

### 5.1 Structure
```json
{
  "release_id": "rel_20260713_a1b2",
  "channel": "candidate",
  "version": "1.2.0.dev0",
  "git_commit": "abc123def456",
  "built_at": "2026-07-13T10:00:00Z",
  "files": [
    {"path": "nous_runtime/__init__.py", "hash": "sha256:..."}
  ],
  "manifest_hash": "sha256:...",
  "signature": "ed25519:..."
}
```

### 5.2 Verification
1. Verify manifest signature against release signing key
2. Verify each file hash against manifest
3. Reject if any hash mismatch
4. Reject if signature invalid

---

## 6. Credential Handling During Updates

### 6.1 Rules
- Candidate uses SEPARATE credentials from stable
- Promotion does NOT copy credentials automatically
- Credential migration is a separate, explicit step
- New credential types needed by candidate: documented in release notes
- Stable credentials never modified during candidate testing

### 6.2 Credential Promotion
1. User explicitly runs: `nous server promote --with-credentials`
2. Credentials copied from stable to candidate config
3. User reviews credential changes
4. User confirms

---

## 7. Health Requirements Per Channel

### 7.1 Development
- Service starts without error
- Basic health endpoint responds

### 7.2 Candidate
- All health checks pass
- No regression vs stable in: test pass rate, lint findings, security findings
- Smoke tests pass
- Provider connectivity verified

### 7.3 Stable
- All metrics within normal range
- Continuous monitoring active
- Backup schedule active
- Supervisor watching process

---

## 8. Prohibited Operations

| Operation | Reason |
|---|---|
| Hot self-modification of running code | Undefined behavior, crash risk |
| Automatic promotion without human approval | Security: no autonomous self-modification |
| Credential sharing between channels | Security: candidate compromise -> stable compromise |
| Data directory sharing between channels | Data corruption risk |
| Destructive database migrations | Rollback must be possible |
