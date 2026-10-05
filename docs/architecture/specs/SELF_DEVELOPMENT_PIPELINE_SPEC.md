# Self-Development Pipeline Specification v1.0

> Status: Draft — Phase 0.5 — Design only, NOT IMPLEMENTED
> Defines how Nous safely modifies its own source code

---

## 1. Pipeline Overview

```
1. CREATE ISOLATED WORKTREE
2. CREATE DEVELOPMENT BRANCH
3. PRODUCE CHANGE PLAN
4. EXECUTE CHANGES
5. RUN COMPILE AND LINT
6. RUN TESTS
7. RUN SECURITY SCAN
8. GENERATE DIFF AND REPORT
9. REQUEST APPROVAL          ◄── HUMAN REQUIRED
10. BUILD CANDIDATE RELEASE
11. DEPLOY CANDIDATE INSTANCE
12. RUN HEALTH CHECKS
13. PROMOTE OR ROLLBACK
```

---

## 2. Step Details

### Step 1: Create Isolated Worktree
- `git worktree add --detach {workspace_path} {base_branch}`
- Workspace is isolated from running instance
- Ensure clean base (no uncommitted changes)

### Step 2: Create Development Branch
- `git checkout -b nous/dev/{work_item_id[:12]}`
- Branch is clean, not detached HEAD
- Record branch name for later steps

### Step 3: Produce Change Plan
- Analyze WorkItem requirements
- Identify files to modify
- Estimate risk level per file
- Produce ordered list of changes
- Record as Checkpoint (immutable)

### Step 4: Execute Changes
- Apply code changes file by file
- Each change within capability + workspace boundaries
- Record each change as ExecutionEvent
- Validate syntax after each file: `python -c "compile(open('file').read(), 'file', 'exec')"`

### Step 5: Run Compile and Lint
- `python -m compileall {workspace_path}` — all Python files must compile
- `ruff check {workspace_path}` — lint must pass
- Record results as ProjectArtifact(type=lint_results)
- **Gate**: Must pass. Failure stops pipeline.

### Step 6: Run Tests
- `pytest {workspace_path}/tests -q` — all tests must pass
- `pytest -q -W error` — no warnings as errors
- Record results as ProjectArtifact(type=test_results)
- **Gate**: Must pass. Failure stops pipeline.

### Step 7: Run Security Scan
- `python scripts/security_scan.py {workspace_path}` — no HIGH findings
- Additional checks: no new secrets, no debug endpoints, no shell=True
- Record results as ProjectArtifact(type=scan_results)
- **Gate**: Must pass. Failure stops pipeline.

### Step 8: Generate Diff and Report
- `git diff {base_branch}` -> diff.patch
- Generate change summary (files changed, lines added/removed, risk assessment)
- Record as ProjectArtifact(type=diff, type=report)

### Step 9: Request Approval
- Present to user: diff, report, test results, scan results, risk assessment
- User reviews all artifacts
- User explicitly approves or rejects
- **Gate**: HUMAN REQUIRED. Model output cannot approve.
- Record approval decision as Checkpoint (immutable, includes approver identity)

### Step 10: Build Candidate Release
- Create release package from workspace
- Hash all files (SHA-256)
- Sign release manifest
- Record hashes as Checkpoint

### Step 11: Deploy Candidate Instance
- Deploy to isolated port (stable_port + 1)
- Use isolated data directory (data/candidate/)
- Use isolated credentials (candidate-specific)
- Start candidate process
- Wait for healthy startup

### Step 12: Run Health Checks
- Health endpoint: `GET /api/v1/health`
- Smoke tests: basic task submission + execution
- Provider connectivity: verify LLM provider reachable
- Performance baseline: compare with stable metrics
- **Gate**: All checks must pass.

### Step 13: Promote or Rollback
- If all health checks pass:
  - Stop stable instance
  - Promote candidate to stable (port swap or symlink swap)
  - Start new stable instance
  - Verify health
  - Record promotion decision
- If any check fails:
  - Stop candidate instance
  - Clean candidate data directory
  - Record rollback decision with failure reason
  - Stable instance continues unaffected

---

## 3. Required Invariants

| Invariant | Enforcement |
|---|---|
| Stable instance never overwrites own running source | Worktree isolation (Step 1) |
| Model output cannot approve promotion | Human approval gate (Step 9) |
| Candidate uses isolated ports and state | Port offset + data directory isolation (Step 11) |
| Migrations support dry-run | Migration test against data copy before deployment |
| Rollback always available | Previous stable release preserved until promotion confirmed |
| Approval evidence persisted | Checkpoint record immutable (Step 9) |
| Release artifacts hashed | SHA-256 of all files, manifest signed (Step 10) |
| Credentials not silently replaced | Candidate uses separate credentials (Step 11) |
| Stable Control Plane available during candidate testing | Candidate on separate port (Step 11) |

---

## 4. Failure Modes

| Failure Point | Behavior |
|---|---|
| Compile/lint failure (Step 5) | Pipeline stops. Error reported. No deployment. |
| Test failure (Step 6) | Pipeline stops. Test output saved as artifact. |
| Security scan failure (Step 7) | Pipeline stops. Findings reported. Must be resolved. |
| User rejects approval (Step 9) | Pipeline stops. Workspace preserved for iteration. |
| Build failure (Step 10) | Pipeline stops. Build error reported. |
| Candidate fails to start (Step 11) | Rollback. Candidate cleaned. |
| Health check failure (Step 12) | Automatic rollback. Candidate stopped and cleaned. |
| Promotion failure (Step 13) | Stable instance restarted from backup. Candidate cleaned. |

---

## 5. What This Pipeline Does NOT Cover

- Hot-patching running instances (not supported)
- Database rollback (migrations must be backward-compatible)
- Multi-node coordinated deployment (future)
- A/B testing or canary deployment (future)
- Automatic dependency updates (requires separate security review)
