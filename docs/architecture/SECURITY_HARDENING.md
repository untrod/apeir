# Security Hardening v1.1

## Pre-Release Security Review

### 1. Installation Security

| Check | Status |
|-------|:------:|
| No secrets in install scripts | Yes |
| pip package has no post-install hooks | Yes |
| Docker image runs as non-root | Warning v1.1 |
| Systemd service uses `NoNewPrivileges` | Yes |
| Windows installer requests minimal permissions | Yes |

### 2. Signature Verification

| Check | Status |
|-------|:------:|
| Pack manifests support `signature` field | Warning v1.2 |
| Provider code is not sandboxed (Python limitation) | Warning Documented |
| Capability execution has risk gating | Yes |
| HMAC signing for Agent commands | Yes |

### 3. Permissions

```yaml
# Pack must declare required permissions
permissions:
  - read:knowledge       # Read from knowledge store
  - write:knowledge      # Write to knowledge store
  - execute:shell        # Run shell commands
  - execute:code         # Run arbitrary code
  - manage:devices       # Register devices
  - manage:providers     # Register providers
  - manage:packs         # Install/remove packs
  - access:secrets       # Read encrypted secrets
```

### 4. Sandbox

| Level | Description |
|-------|-------------|
| **None** | No restrictions (trusted providers only) |
| **Process** | Subprocess isolation (planned v1.2) |
| **Container** | Docker/podman isolation (planned v2.0) |

### 5. Provider Credentials

| Rule |
|------|
| Credentials loaded from environment variables only |
| Never hardcoded in provider code |
| Never logged (auto-masked in audit) |
| Scoped per-provider, not global |
| Rotated on provider reconnect |

### 6. Secret Management

```
Priority:
1. Environment variable (NOUS_LLM_API_KEY)
2. .env file (gitignored)
3. config.local.json (gitignored)
Never: hardcoded in source, committed to git, in documentation
```

### 7. Pre-Release Checklist

- [ ] `grep -r "sk-" . --include="*.py" --include="*.md"` -> 0 results
- [ ] `grep -r "api.key" . --include="*.py"` -> 0 results
- [ ] `.gitignore` covers all secret patterns
- [ ] `nous doctor` reports no security warnings
- [ ] All provider credentials come from env vars
- [ ] Audit log masks sensitive fields
- [ ] Rate limiting enabled for public-facing endpoints
