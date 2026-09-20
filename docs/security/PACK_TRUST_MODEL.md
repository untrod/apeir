# Pack Trust Model v1.0

## Trust Levels

| Level | Source | Install Warning | Sandbox | Auto-update |
|-------|--------|:--------------:|:-------:|:----------:|
| **Official** | Nous project | None | None | Yes |
| **Community** | Public registry | "Community pack" | Optional | Opt-in |
| **Untrusted** | Unknown | "UNTRUSTED — review code" | Forced | No |

## Manifest Permissions

Packs declare required permissions:
```yaml
permissions:
  - read:knowledge
  - execute:shell      # Warning HIGH RISK
  - access:secrets     # Warning CRITICAL
```

## Runtime Admission

For v1.0:
1. Pack installed from local directory -> user inherently trusts it
2. Manifest permissions are checked against Runtime policy
3. HIGH/CRITICAL capabilities require user confirmation per execution
4. Audit log records all pack activity

## Future: Signature Verification (v1.2+)

```yaml
# pack.yaml
signature:
  algorithm: ed25519
  public_key: "..."
  signature: "..."
```

Runtime verifies signature before installation.

## Current Limitations

- Python packs can execute arbitrary code (no process sandbox)
- No code review for community packs
- Provider code runs in the same process as Runtime

## Recommendations for Users

1. Only install packs from sources you trust
2. Review `pack.yaml` permissions before installing
3. Run `nous doctor` after installing a new pack
4. Monitor audit logs for unexpected capability usage
