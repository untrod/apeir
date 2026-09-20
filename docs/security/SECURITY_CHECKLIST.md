# Security Checklist

## Before Deployment
- [ ] `.env` is `chmod 600`, not in git
- [ ] `AUTH_TOKEN` is strong random, not default
- [ ] `AGENT_SIGNING_SECRET` is strong random
- [ ] All HIGH-risk capabilities disabled unless needed
- [ ] Brain behind firewall or WireGuard
- [ ] Dashboard requires token
- [ ] Log files rotated (10MB default)

## Capability Audit
- [ ] All capabilities have `risk_level` set
- [ ] HIGH/CRITICAL require `requires_approval: true`
- [ ] No capability bypasses audit

## Regular Checks
- [ ] Run `bash scripts/nous-doctor.sh` weekly
- [ ] Review `/api/v1/kernel/security` monthly
- [ ] Check audit logs for anomalies
