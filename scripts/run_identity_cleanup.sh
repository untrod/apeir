#!/usr/bin/env bash
# ============================================================================
# Nous Repository Identity Cleanup — Manual Execution Script
# ============================================================================
# Run this script from the repository root to complete all hygiene tasks
# that require git access.
#
# Usage: bash scripts/run_identity_cleanup.sh [--dry-run]
# ============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
    echo -e "${YELLOW}[DRY RUN] No changes will be made.${NC}"
fi

# ── Step 1: Audit current state ──────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 1: Current State Audit"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "Current branch:"
git branch --show-current

echo ""
echo "All branches:"
git branch -a

echo ""
echo "Branches with tool prefixes:"
git branch -a | grep -E 'codex/|claude/|ai/|agent-' || echo "  (none found)"

echo ""
echo "Git identity:"
echo "  user.name:  $(git config user.name)"
echo "  user.email: $(git config user.email)"

echo ""
echo "Running identity audit..."
python scripts/repository_identity_audit.py || true

# ── Step 2: Rename branches ──────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 2: Branch Rename"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

rename_branch() {
    local old_name="$1"
    local new_name="$2"

    if git branch --list "$old_name" | grep -q .; then
        echo ""
        echo "Renaming: $old_name → $new_name"
        if [ "$DRY_RUN" = false ]; then
            git branch -m "$old_name" "$new_name"
            echo -e "${GREEN}  Done.${NC}"
        else
            echo -e "${YELLOW}  (dry run)${NC}"
        fi
    else
        echo "  Branch '$old_name' not found — skipping."
    fi
}

rename_branch "codex/unified-model-runtime" "kernel/unified-model-runtime"
rename_branch "codex/archive-rc3-local-fd66c83" "archive/rc3-fd66c83"
rename_branch "codex/archive-ci-sbom-local-f6704a9" "archive/ci-sbom-f6704a9"

# ── Step 3: Remote cleanup ───────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 3: Remote Cleanup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if git branch -r | grep -q 'origin/codex/unified-model-runtime'; then
    echo ""
    echo "Remote has origin/codex/unified-model-runtime — deleting..."
    if [ "$DRY_RUN" = false ]; then
        git push origin --delete codex/unified-model-runtime
        echo -e "${GREEN}  Done.${NC}"
    else
        echo -e "${YELLOW}  (dry run)${NC}"
    fi
else
    echo "  Remote codex/unified-model-runtime not found — skipping."
fi

# Push renamed branch
if git branch --list "kernel/unified-model-runtime" | grep -q .; then
    echo ""
    echo "Pushing kernel/unified-model-runtime..."
    if [ "$DRY_RUN" = false ]; then
        git push origin kernel/unified-model-runtime
        git branch -u origin/kernel/unified-model-runtime
        echo -e "${GREEN}  Done.${NC}"
    else
        echo -e "${YELLOW}  (dry run)${NC}"
    fi
fi

# ── Step 4: Install pre-push hook ────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 4: Install Pre-Push Hook"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

HOOK_SRC="scripts/pre-push-hook.sh"
HOOK_DST=".git/hooks/pre-push"

if [ -f "$HOOK_SRC" ]; then
    if [ "$DRY_RUN" = false ]; then
        cp "$HOOK_SRC" "$HOOK_DST"
        chmod +x "$HOOK_DST"
        echo -e "${GREEN}  Hook installed to .git/hooks/pre-push${NC}"
    else
        echo -e "${YELLOW}  (dry run) Would install to .git/hooks/pre-push${NC}"
    fi
else
    echo -e "${RED}  Hook script not found: $HOOK_SRC${NC}"
fi

# ── Step 5: Verify ───────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Step 5: Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "Branches after cleanup:"
git branch -a

echo ""
echo "Checking for remaining tool-prefixed branches..."
REMAINING=$(git branch -a | grep -E 'codex/|claude/|ai/|agent-' || true)
if [ -z "$REMAINING" ]; then
    echo -e "${GREEN}  No tool-prefixed branches remain.${NC}"
else
    echo -e "${RED}  Still found:${NC}"
    echo "$REMAINING"
fi

echo ""
echo "Running identity audit one final time..."
python scripts/repository_identity_audit.py && echo -e "${GREEN}  Identity audit passed.${NC}" || echo -e "${RED}  Identity audit found issues. Review and fix before release.${NC}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Cleanup Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "  1. Verify: git branch -a  (no codex/ branches)"
echo "  2. Enable branch protection on 'main' in GitHub settings"
echo "  3. Push cleaned branches: git push --all origin"
echo "  4. Review the identity audit report: docs/audit/REPOSITORY_IDENTITY_AUDIT.md"
echo "  5. Work through: docs/audit/PUBLIC_RELEASE_CHECKLIST.md"
echo ""
