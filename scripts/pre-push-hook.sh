#!/usr/bin/env bash
# Pre-push hook: block branches with AI-tool naming prefixes.
#
# Install: copy to .git/hooks/pre-push (or use core.hooksPath)
#
# This hook prevents accidentally pushing branches whose names reference
# development tools (codex, claude, ai, agent, etc.) to the public remote.
# Branch names should describe the work, not the tools used to do it.

set -euo pipefail

remote="$1"
remote_url="$2"

FORBIDDEN_PREFIXES=(
    "codex/"
    "claude/"
    "gpt/"
    "ai/"
    "chatgpt/"
    "copilot/"
    "agent-upload/"
    "auto-generated/"
    "claude-code/"
    "openai/"
)

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

for prefix in "${FORBIDDEN_PREFIXES[@]}"; do
    if [[ "$CURRENT_BRANCH" == "$prefix"* ]]; then
        cat >&2 <<EOF
╔══════════════════════════════════════════════════════════════╗
║  BRANCH NAME REJECTED                                       ║
║                                                              ║
║  Branch: ${CURRENT_BRANCH}
║  Prefix: ${prefix}
║                                                              ║
║  Branch names must not reference AI tools or automation.     ║
║  See CONTRIBUTING.md § Branch naming for allowed prefixes.   ║
║                                                              ║
║  Rename before pushing:                                      ║
║    git branch -m ${CURRENT_BRANCH} feature/your-description  ║
╚══════════════════════════════════════════════════════════════╝
EOF
        exit 1
    fi
done

# Also run identity audit if available
AUDIT_SCRIPT="$(git rev-parse --show-toplevel)/scripts/repository_identity_audit.py"
if [ -f "$AUDIT_SCRIPT" ] && command -v python &>/dev/null; then
    echo "→ Running repository identity audit..."
    python "$AUDIT_SCRIPT" || {
        cat >&2 <<EOF
╔══════════════════════════════════════════════════════════════╗
║  IDENTITY AUDIT FAILED                                       ║
║                                                              ║
║  The repository identity audit found AI attribution          ║
║  patterns in code or documentation.                          ║
║                                                              ║
║  Fix the reported issues before pushing.                     ║
╚══════════════════════════════════════════════════════════════╝
EOF
        exit 1
    }
    echo "  Identity audit passed."
fi

exit 0
