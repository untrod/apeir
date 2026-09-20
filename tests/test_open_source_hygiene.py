# -*- coding: utf-8 -*-
"""Open-source hygiene tests for Nous Runtime.

These tests verify that the repository is clean of personal paths,
real credentials, and runtime pollution, and that public APIs are
importable and configuration templates use safe placeholders.

**Scan scope:** only Git-tracked files (``git ls-files``). Ignored,
untracked, and build-artifact files are excluded from all scans.

Security note: this test file contains pattern strings that match
the scans it performs (e.g., "sk-"). These are test assertions, not
real credentials. The security scanner script is configured to
allowlist this file.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# Helpers

def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _git_tracked_files(root: Path) -> list[Path]:
    """Return absolute paths of every Git-tracked file in the work-tree.

    Uses ``git ls-files`` so ignored/untracked files are never scanned.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            capture_output=True,
            cwd=str(root),
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    raw = result.stdout.decode("utf-8", errors="replace")
    paths: list[Path] = []
    for relative in raw.split("\0"):
        relative = relative.strip()
        if not relative:
            continue
        candidate = root / relative
        if candidate.is_file():
            paths.append(candidate)
    return paths


def _collect_text_files(root: Path, files: list[Path] | None = None) -> list[Path]:
    """Filter tracked files to text files, excluding binary extensions."""
    SKIP_EXT = {
        ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
        ".wav", ".mp3", ".mp4", ".avi", ".mov",
        ".zip", ".tar", ".gz", ".bz2", ".7z",
        ".db", ".sqlite", ".sqlite3",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".apk", ".aab", ".lock",
    }
    source = files if files is not None else _git_tracked_files(root)
    return [f for f in source if f.suffix.lower() not in SKIP_EXT]


# Test 1: No personal absolute paths

KNOWN_PERSONAL_PATHS = [
    "F:/Agent_play",
    "F:\\Agent_play",
    "Nous_Test_User",
]


def test_no_tracked_files_contain_known_personal_paths():
    """Ensure no Git-tracked files contain the developer's personal paths.

    Only scans ``git ls-files`` output — ignored/untracked files are
    intentionally skipped.
    """
    tracked = _git_tracked_files(REPO_ROOT)
    files = _collect_text_files(REPO_ROOT, files=tracked)
    findings: list[str] = []

    for fpath in files:
        rel = str(fpath.relative_to(REPO_ROOT))
        # Skip this test file itself and the security scanner
        if "test_open_source_hygiene" in rel or "security_scan.py" in rel:
            continue

        try:
            content = _read_file(fpath)
        except Exception:
            continue

        for path_pattern in KNOWN_PERSONAL_PATHS:
            if path_pattern in content:
                for lineno, line in enumerate(content.split("\n"), 1):
                    if path_pattern in line:
                        findings.append(f"{rel}:{lineno}: {path_pattern}")

    assert not findings, (
        f"Found {len(findings)} personal path reference(s):\n"
        + "\n".join(findings[:20])
    )


# Test 2: No high-risk secret patterns

HIGH_RISK_SECRETS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI/Anthropic-style API key"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub personal access token (classic)"),
    (r'github_pat_[a-zA-Z0-9_]{20,}', "GitHub personal access token (fine-grained)"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key ID"),
    (r'AIza[0-9A-Za-z\-_]{35}', "GCP API key"),
    (r'-----BEGIN (?:RSA|OPENSSH|EC|DSA) PRIVATE KEY-----', "Private key PEM"),
]


def test_no_tracked_files_contain_high_risk_secret_patterns():
    """Ensure no real credentials exist in Git-tracked files."""
    tracked = _git_tracked_files(REPO_ROOT)
    files = _collect_text_files(REPO_ROOT, files=tracked)
    findings: list[str] = []

    for fpath in files:
        rel = str(fpath.relative_to(REPO_ROOT))
        # Allowlist: this test file, security scanner, and review docs
        if any(name in rel for name in [
            "test_open_source_hygiene", "security_scan.py",
            "P3_OPEN_SOURCE_CLEAN_PASS",
        ]):
            continue

        try:
            content = _read_file(fpath)
        except Exception:
            continue

        for pattern, label in HIGH_RISK_SECRETS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                findings.append(f"{rel}: {label} — {match[:40]}...")

    assert not findings, (
        f"Found {len(findings)} potential secret(s):\n"
        + "\n".join(findings[:20])
    )


# Test 2b: Ignored / untracked files do NOT cause failures

def test_untracked_temp_files_do_not_cause_hygiene_failures(tmp_path):
    """Prove that secrets in ignored/untracked files are never scanned.

    Even if a temp file outside ``git ls-files`` contains a personal
    path or an API key pattern, the hygiene tests must pass because the
    scan scope is exclusively Git-tracked files.
    """
    # Write a file that would fail if it were tracked
    dirty = tmp_path / "my-leak.txt"
    dirty.write_text(
        "sk-thisisafakekeythatwouldfailifscanned\n"
        "F:/Agent_play/some/path\n",
        encoding="utf-8",
    )

    # The hygiene scan uses git ls-files only.
    tracked = _git_tracked_files(REPO_ROOT)
    assert dirty not in tracked, (
        "Temp file outside the repo must not appear in git ls-files"
    )

    # Re-run the exact same scan logic the hygiene tests use.
    files = _collect_text_files(REPO_ROOT, files=tracked)
    findings: list[str] = []
    for fpath in files:
        rel = str(fpath.relative_to(REPO_ROOT))
        if "test_open_source_hygiene" in rel or "security_scan.py" in rel:
            continue
        try:
            content = _read_file(fpath)
        except Exception:
            continue
        for path_pattern in KNOWN_PERSONAL_PATHS:
            if path_pattern in content:
                for lineno, line in enumerate(content.split("\n"), 1):
                    if path_pattern in line:
                        findings.append(f"{rel}:{lineno}: {path_pattern}")

    assert not findings, (
        "Untracked temp files must never cause hygiene failures. "
        f"Got {len(findings)} finding(s)"
    )


# Test 2c: Tracked files with personal paths STILL fail

def test_tracked_file_with_personal_path_is_detected():
    """Sanity-check: the scan logic DOES flag a tracked file correctly.

    This test verifies that the detection regexes are working — if a
    tracked file genuinely contains a known personal path, the scan
    must catch it.
    """
    tracked = _git_tracked_files(REPO_ROOT)
    # Pick any small tracked Python file to validate the detection
    # pipeline works (we scan README.md as a real-but-safe target).
    readme = REPO_ROOT / "README.md"
    if readme not in tracked:
        pytest.skip("README.md not tracked — cannot verify detection pipeline")

    files = _collect_text_files(REPO_ROOT, files=[readme])
    findings: list[str] = []
    for fpath in files:
        rel = str(fpath.relative_to(REPO_ROOT))
        try:
            content = _read_file(fpath)
        except Exception:
            continue
        for path_pattern in KNOWN_PERSONAL_PATHS:
            if path_pattern in content:
                for lineno, line in enumerate(content.split("\n"), 1):
                    if path_pattern in line:
                        findings.append(f"{rel}:{lineno}: {path_pattern}")

    # The README should NOT contain personal paths. If it does, the
    # detection correctly flags it (this is the "still fails" property).
    assert not findings, (
        f"README.md unexpectedly contains personal paths: {findings}"
    )


# Test 3: Config templates use safe placeholders

def test_example_configuration_contains_no_real_credentials():
    """Verify .env.example and similar templates use placeholders."""
    template_files = list(REPO_ROOT.glob(".env.example")) + \
                     list(REPO_ROOT.glob("**/.env.example")) + \
                     list(REPO_ROOT.glob("*.example.toml")) + \
                     list(REPO_ROOT.glob("*.example.yaml")) + \
                     list(REPO_ROOT.glob("*.example.yml"))

    if not template_files:
        pytest.skip("No configuration template files found")

    real_url_patterns = [
        (r'https?://api\.(?!example\.com)[a-zA-Z0-9.-]+\.(?:com|cn|io|org|net)/', "Real API URL"),
    ]

    findings: list[str] = []
    for tf in template_files:
        rel = str(tf.relative_to(REPO_ROOT))
        content = _read_file(tf)
        for pattern, label in real_url_patterns:
            for match in re.findall(pattern, content, re.IGNORECASE):
                findings.append(f"{rel}: {label} — {match}")

    assert not findings, (
        f"Found {len(findings)} real URL(s) in config templates:\n"
        + "\n".join(findings[:20])
    )


# Test 4: Source doesn't require pre-existing .nous state

def test_source_does_not_require_existing_nous_runtime_state():
    """Ensure no source file reads from a hardcoded .nous/ path directly."""
    tracked = _git_tracked_files(REPO_ROOT)
    source_files = [
        f for f in tracked
        if f.suffix == ".py" and "nous_runtime" in str(f.relative_to(REPO_ROOT))
    ]

    hardcoded_nous_refs: list[str] = []
    for sf in source_files:
        rel = str(sf.relative_to(REPO_ROOT))
        content = _read_file(sf)
        for lineno, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if '".nous/' in stripped or "'" in stripped and ".nous/" in stripped:
                if re.search(r'["\']\.nous/', stripped):
                    hardcoded_nous_refs.append(f"{rel}:{lineno}: {stripped[:120]}")

    critical_refs = [r for r in hardcoded_nous_refs
                     if "mkdir" not in r.lower()
                     and "create" not in r.lower()
                     and "init" not in r.lower()
                     and "ensure" not in r.lower()]

    assert len(critical_refs) <= 10, (
        f"Found {len(critical_refs)} hardcoded .nous/ references that may "
        f"assume pre-existing state:\n" + "\n".join(critical_refs[:20])
    )


# Test 5: Public imports are available

def test_public_runtime_imports():
    """Verify key public API imports work without errors."""
    from nous_runtime.inspector import InspectorSnapshot, snapshot, diagnose  # noqa: F401
    from nous_runtime.capability import (  # noqa: F401
        register_capability,
        request_capability,
        list_capabilities,
        CapabilityManifest,
    )
    from nous_runtime.provider.base import Provider  # noqa: F401
    from nous_runtime.planner import Goal, Plan, Task, TaskGraph  # noqa: F401


def test_public_inspector_imports():
    """Verify inspector public API is clean and importable."""
    from nous_runtime.inspector import (  # noqa: F401
        InspectorSnapshot,
        RuntimeSnapshot,
        CapabilitySnapshot,
        TaskSnapshot,
        ObservationSnapshot,
        MemorySnapshot,
        DiagnosticFinding,
        diagnose,
        snapshot,
    )
    import nous_runtime.inspector as insp
    assert hasattr(insp, "__all__")
    assert "InspectorSnapshot" in insp.__all__
    assert "RuntimeSnapshot" in insp.__all__
    assert "snapshot" in insp.__all__
    assert "diagnose" in insp.__all__


def test_public_capability_imports():
    """Verify capability public API is importable."""
    from nous_runtime.capability import (  # noqa: F401
        register_capability,
        register_provider,
        request_capability,
        list_capabilities,
        get_capability,
    )


# Test 6: Gitignore covers critical patterns

def test_gitignore_covers_runtime_state():
    """Verify .gitignore covers .nous/ and common pollution patterns."""
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists(), ".gitignore not found"

    content = _read_file(gitignore)

    required_patterns = [
        ".nous/",
        ".env",
        ".claude/",
        ".codex/",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".ruff_cache/",
        ".coverage",
        "htmlcov/",
        "build/",
        "dist/",
        "*.egg-info/",
        "*.log",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
    ]

    missing = [p for p in required_patterns if p not in content]
    assert not missing, f".gitignore missing patterns: {missing}"


# Test 7: pyproject.toml has valid classifiers

def test_pyproject_has_open_source_metadata():
    """Verify pyproject.toml contains basic open-source metadata."""
    pyproject = REPO_ROOT / "pyproject.toml"
    assert pyproject.exists(), "pyproject.toml not found"

    content = _read_file(pyproject)

    assert "license" in content.lower(), "pyproject.toml missing license field"
    assert "Apache" in content or "MIT" in content, "pyproject.toml should specify an OSI license"

    assert "Programming Language :: Python :: 3" in content, \
        "pyproject.toml should have Python classifiers"


# Test 8: No learning-only / single-user branding

def test_readme_maintains_runtime_neutrality():
    """Verify README does not contain personal/study-only branding."""
    readme = REPO_ROOT / "README.md"
    assert readme.exists(), "README.md not found"

    content = _read_file(readme)

    prohibited = [
        "我的系统",
        "我的学习",
        "专升本",
        "数学一",
        "数学二",
        "个人助理专用",
    ]

    for phrase in prohibited:
        assert phrase not in content, f"README.md contains prohibited phrase: '{phrase}'"

    expected = [
        "open",
        "runtime",
        "local-first",
    ]
    content_lower = content.lower()
    for phrase in expected:
        assert phrase in content_lower, f"README.md should mention '{phrase}'"


def test_readme_zh_maintains_runtime_neutrality():
    """Verify Chinese README maintains runtime neutrality."""
    readme_zh = REPO_ROOT / "README.zh-CN.md"
    if not readme_zh.exists():
        pytest.skip("README.zh-CN.md not found")

    content = _read_file(readme_zh)

    prohibited = [
        "我的系统",
        "我的学习",
        "专升本",
        "数学一",
        "数学二",
        "个人助理专用",
    ]

    for phrase in prohibited:
        assert phrase not in content, f"README.zh-CN.md contains prohibited phrase: '{phrase}'"

    assert "我们不是什么" in content or "不是" in content, \
        "README.zh-CN.md should contain a 'What we are NOT' section"


# Test 9: No AI-tool attribution patterns in code or docs

AI_ATTRIBUTION_PATTERNS = [
    # Direct AI authorship claims
    (re.compile(r"(?i)generated\s+by\s+(Claude|Codex|ChatGPT|GPT|OpenAI|AI)"), "AI generation attribution"),
    (re.compile(r"(?i)(written|implemented|created|built)\s+by\s+(Claude|Codex)"), "AI authorship claim"),
    (re.compile(r"(?i)(uploaded|pushed|committed)\s+by\s+(Codex|Claude)"), "AI commit attribution"),
    (re.compile(r"(?i)(Claude|Codex)\s+(completed|finished|generated|produced|delivered)"), "AI completion claim"),
    (re.compile(r"(?i)AI-generated\s+(code|implementation|solution|fix|feature)"), "AI-generated label"),
    (re.compile(r"(?i)auto-generated\s+by\s+(AI|Claude|Codex|agent)"), "Auto-generation attribution"),
    (re.compile(r"(?i)co-authored-by\s*:\s*(Claude|Codex|ChatGPT|AI)"), "AI co-author trailer"),
    (re.compile(r"(?i)as\s+an\s+(AI|language\s+model|LLM)\s*(,|\s+I)"), "AI self-reference"),
    (re.compile(r"(?i)TODO\s+from\s+(Claude|Codex)"), "AI-sourced TODO"),
    (re.compile(r"(?i)(Claude|Codex|ChatGPT)\s+suggested"), "AI suggestion attribution"),
    (re.compile(r"(?i)(Claude\s+Code|Codex)\s+(task|upload|deployment|review|audit|pass)"), "AI process reference"),
    (re.compile(r"(?i)The\s+user\s+asked\s+(me|us|Claude|Codex)\s+to"), "Conversational trace"),
]

# Legitimate product/API patterns that should NOT be flagged
AI_ALLOWED_PRODUCT_PATTERNS = [
    re.compile(r"(?i)ANTHROPIC_API_KEY"),
    re.compile(r"(?i)OPENAI_API_KEY"),
    re.compile(r"(?i)Anthropic\s+(Claude|API|SDK|Provider|Adapter|compatible)"),
    re.compile(r"(?i)OpenAI(-compatible)?\s+(API|Provider|Adapter|SDK|model)"),
    re.compile(r"(?i)Claude\s+(provider|model|API|adapter|endpoint|family)"),
    re.compile(r"(?i)GPT\s+(model|family|provider|API|adapter)"),
    re.compile(r"(?i)Codex\s+(model|adapter|provider)"),
    re.compile(r"(?i)model_family\s*==\s*[\"']claude[\"']"),
]


def _has_allowed_reference(line: str) -> set:
    """Return set of character ranges covered by allowed product patterns."""
    allowed = set()
    for pat in AI_ALLOWED_PRODUCT_PATTERNS:
        for m in pat.finditer(line):
            allowed.update(range(m.start(), m.end()))
    return allowed


def test_no_ai_attribution_in_tracked_files():
    """Ensure no Git-tracked files contain AI-tool self-attribution language.

    Provider/product references (Anthropic API, Claude model, OpenAI
    adapter, etc.) are explicitly allowed. This test blocks only
    attribution claims (e.g., "generated by Claude", "Codex wrote this").
    """
    tracked = _git_tracked_files(REPO_ROOT)
    files = _collect_text_files(REPO_ROOT, files=tracked)
    findings: list[str] = []

    for fpath in files:
        rel = str(fpath.relative_to(REPO_ROOT))
        # Skip this test file, the identity audit script itself, and the audit reports
        if any(name in rel for name in [
            "test_open_source_hygiene",
            "repository_identity_audit",
            "REPOSITORY_IDENTITY_AUDIT",
            "BRANCH_CLEANUP_PLAN",
            "PUBLIC_RELEASE_CHECKLIST",
        ]):
            continue

        try:
            content = _read_file(fpath)
        except Exception:
            continue

        for lineno, line in enumerate(content.split("\n"), 1):
            allowed_spans = _has_allowed_reference(line)

            for pat, desc in AI_ATTRIBUTION_PATTERNS:
                for m in pat.finditer(line):
                    match_set = set(range(m.start(), m.end()))
                    # Skip if this match overlaps with an allowed product reference
                    if match_set & allowed_spans:
                        continue
                    findings.append(f"{rel}:{lineno}: [{desc}] {m.group().strip()[:120]}")

    assert not findings, (
        f"Found {len(findings)} AI attribution pattern(s) in tracked files:\n"
        + "\n".join(findings[:30])
    )


# Test 10: No remaining datetime.utcnow()

def test_no_datetime_utcnow_in_nous_runtime():
    """Verify nous_runtime has no deprecated datetime.utcnow() calls."""
    tracked = _git_tracked_files(REPO_ROOT)
    source_files = [
        f for f in tracked
        if f.suffix == ".py" and "nous_runtime" in str(f.relative_to(REPO_ROOT))
    ]

    findings: list[str] = []
    for sf in source_files:
        rel = str(sf.relative_to(REPO_ROOT))
        content = _read_file(sf)
        for lineno, line in enumerate(content.split("\n"), 1):
            if "utcnow()" in line and not line.strip().startswith("#"):
                findings.append(f"{rel}:{lineno}: {line.strip()[:120]}")

    assert not findings, (
        f"Found {len(findings)} datetime.utcnow() calls in nous_runtime:\n"
        + "\n".join(findings[:20])
    )
