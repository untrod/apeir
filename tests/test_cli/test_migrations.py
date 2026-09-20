# -*- coding: utf-8 -*-
"""Database initialization & migration regression tests.

These tests verify that the database bootstrap path works correctly,
especially for the installed-package scenario where migration .sql files
may not be present on disk.
"""

import os
import sys
import tempfile

import pytest

# Ensure project root is on path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


# Expected tables from all 14 migrations

REQUIRED_TABLES = {
    "schema_migrations",
    "events",
    "jobs",
    "devices",
    "notifications",
    "automation_rules",
    "automation_log",
    "audit_logs",
    "inbox",
    "study_sessions",
    "session_questions",
    "session_mistakes",
    "capabilities",
    "capability_edges",
    "capability_executions",
    "reasoning_traces",
    "trace_steps",
    "observer_logs",
    "security_events",
    "stability_snapshots",
}


# Helpers

def _get_existing_tables() -> set[str]:
    """Return set of user-table names currently in nous_core.db."""
    from remote_terminal.nous_core.db import connect
    with connect(readonly=True) as db:
        rows = db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    return {r["name"] for r in rows}


# Tests

class TestBootstrapCoreTables:
    """Direct tests for bootstrap_core_tables()."""

    def test_bootstrap_creates_all_required_tables(self):
        """bootstrap_core_tables must create every expected table."""
        from remote_terminal.nous_core.db import bootstrap_core_tables

        created = bootstrap_core_tables()
        existing = _get_existing_tables()

        missing = REQUIRED_TABLES - existing
        assert not missing, f"Missing tables after bootstrap: {missing}"
        assert created >= 0  # may be 0 if tables already existed

    def test_bootstrap_is_idempotent(self):
        """Calling bootstrap_core_tables twice must be safe."""
        from remote_terminal.nous_core.db import bootstrap_core_tables

        bootstrap_core_tables()
        existing_before = _get_existing_tables()

        created_second = bootstrap_core_tables()
        existing_after = _get_existing_tables()

        assert existing_before == existing_after
        # Second call should create 0 new tables
        assert created_second == 0


class TestRunMigrations:
    """Tests for run_migrations() covering both file-based and bootstrap paths."""

    def test_run_migrations_bootstrap_fallback(self, monkeypatch, tmp_path):
        """
        When migrations_dir is missing, run_migrations() must fall back
        to bootstrap_core_tables() and create all required tables.
        """
        from remote_terminal.nous_core.db import run_migrations

        # Temporarily redirect data_dir to a temp location so we get a
        # fresh database.
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        n = run_migrations()
        existing = _get_existing_tables()

        missing = REQUIRED_TABLES - existing
        assert not missing, f"Missing tables after run_migrations (fallback): {missing}"
        # There's no migrations dir in tmp_path, so bootstrap should fire.
        assert n >= 0

    def test_run_migrations_idempotent(self, monkeypatch, tmp_path):
        """Calling run_migrations twice must be safe."""
        from remote_terminal.nous_core.db import run_migrations

        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        run_migrations()
        existing_before = _get_existing_tables()

        run_migrations()
        existing_after = _get_existing_tables()

        assert existing_before == existing_after

    def test_runtime_start_runs_migrations(self, monkeypatch, tmp_path):
        """Runtime.start() must run migrations without error."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from nous_runtime.kernel.runtime import Runtime
        rt = Runtime()
        status = rt.start()
        assert status.running
        assert "migrations" not in [e.lower() for e in status.errors]
        rt.stop()


class TestFreshInstallScenario:
    """End-to-end: `nous init` → pack install → capability list."""

    def test_init_initializes_database(self):
        """nous init (non-wizard) must create all required tables."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            r = subprocess.run(
                [sys.executable, "-m", "nous_runtime.cli.main",
                 "init", "--no-wizard", "--path", tmpdir],
                capture_output=True, text=True, timeout=30,
                cwd=ROOT,
                env={**os.environ, "NOUS_DATA_DIR": os.path.join(tmpdir, "data")},
            )
            # init should not crash
            assert r.returncode == 0, f"nous init failed: {r.stderr}"
            assert "initialized" in r.stdout.lower()

    def test_pack_install_then_capability_list(self, tmp_path):
        """Install hello_pack then list capabilities — no errors."""
        hello_pack_dir = os.path.join(ROOT, "hello_pack")
        if not os.path.isdir(hello_pack_dir):
            pytest.skip("hello_pack directory not found")

        # Isolate: use temp data dir for DB and a fresh PackRegistry
        data_dir = str(tmp_path / "data")
        os.makedirs(data_dir, exist_ok=True)
        os.environ["NOUS_DATA_DIR"] = data_dir

        # Override PACK_REGISTRY_FILE via sys.modules
        import sys
        reg_module = sys.modules["nous_runtime.pack.registry"]
        old_reg_file = reg_module.PACK_REGISTRY_FILE
        reg_tmp = str(tmp_path / "pack_registry.json")
        reg_module.PACK_REGISTRY_FILE = reg_tmp

        try:
            # 1. Init DB
            from remote_terminal.nous_core.db import run_migrations
            run_migrations()

            # 2. Install pack (fresh — registry is isolated to temp file)
            from nous_runtime.pack.registry import PackRegistry
            reg = PackRegistry()
            pack = reg.install(hello_pack_dir)
            assert pack.manifest.name == "hello_pack"

            # 3. List capabilities — must not error, must show hello_pack
            from remote_terminal.nous_core.capability import list_capabilities
            caps = list_capabilities()
            cap_names = [c.get("name", "") for c in caps if isinstance(c, dict)]
            assert isinstance(caps, list)
            # hello_pack.hello should be registered
            assert "hello_pack.hello" in cap_names, \
                f"hello_pack.hello not in capabilities: {cap_names}"
        finally:
            reg_module.PACK_REGISTRY_FILE = old_reg_file

    def test_capability_list_after_bootstrap(self, monkeypatch, tmp_path):
        """list_capabilities() must work after bootstrap without errors."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        from remote_terminal.nous_core.db import run_migrations
        run_migrations()

        from remote_terminal.nous_core.capability import list_capabilities
        caps = list_capabilities()
        # After bootstrap + auto-seed, we expect default capabilities
        assert isinstance(caps, list)


class TestNoRemoteTerminalPathReferences:
    """Regression: error messages must not contain stale file-system paths."""

    def test_db_missing_dir_message_is_info_not_path(self, monkeypatch, tmp_path, caplog):
        """When migrations dir is missing, the log should be INFO level,
        not a confusing DEBUG message about a file path."""
        monkeypatch.setenv("NOUS_DATA_DIR", str(tmp_path))

        import logging
        from remote_terminal.nous_core.db import run_migrations

        caplog.set_level(logging.INFO, logger="nous_core")
        run_migrations()

        # Check that no ERROR or WARNING was emitted about missing dir
        for record in caplog.records:
            assert record.levelno < logging.WARNING, \
                f"Unexpected warning/error: {record.getMessage()}"

    def test_no_hardcoded_remote_terminal_in_messages(self):
        """Bootstrap code must not hardcode 'remote_terminal' in user-facing
        messages or error strings."""
        import inspect
        from remote_terminal.nous_core import db as db_module

        # Check that bootstrap_core_tables doesn't reference remote_terminal
        # in any string literal used for messaging
        src = inspect.getsource(db_module.bootstrap_core_tables)
        # Allow remote_terminal only in comments/docstrings
        for line in src.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            # String literals mentioning remote_terminal
            if "remote_terminal" in stripped:
                # Only flag if it looks like a path reference in a string
                if '"remote_terminal' in stripped or "'remote_terminal" in stripped:
                    pytest.fail(
                        f"bootstrap_core_tables contains remote_terminal "
                        f"reference: {stripped}"
                    )


class TestPackRemoveCleansCapabilities:
    """Regression: removing a pack must unregister its capabilities."""

    def test_remove_clears_capabilities(self, tmp_path):
        """Install → verify caps exist → remove → verify caps gone."""
        import sys as _sys

        hello_pack_dir = os.path.join(ROOT, "hello_pack")
        if not os.path.isdir(hello_pack_dir):
            pytest.skip("hello_pack directory not found")

        data_dir = str(tmp_path / "data")
        os.makedirs(data_dir, exist_ok=True)
        os.environ["NOUS_DATA_DIR"] = data_dir

        # Isolate pack registry — import first so the module is in sys.modules
        import nous_runtime.pack.registry  # noqa: F401
        reg_module = _sys.modules["nous_runtime.pack.registry"]
        old_reg_file = reg_module.PACK_REGISTRY_FILE
        reg_tmp = str(tmp_path / "pack_registry.json")
        reg_module.PACK_REGISTRY_FILE = reg_tmp

        try:
            # 1. Init DB
            from remote_terminal.nous_core.db import run_migrations
            run_migrations()

            # 2. Install pack
            from nous_runtime.pack.registry import PackRegistry
            reg = PackRegistry()
            pack = reg.install(hello_pack_dir)
            assert pack.manifest.name == "hello_pack"

            # 3. Verify capability visible
            from remote_terminal.nous_core.capability import list_capabilities
            caps = list_capabilities()
            cap_names = [c.get("name", "") for c in caps if isinstance(c, dict)]
            assert "hello_pack.hello" in cap_names, \
                f"Expected hello_pack.hello in capabilities after install, got: {cap_names}"

            # 4. Remove pack
            reg.remove("hello_pack")

            # 5. Verify pack not in registry
            packs = reg.list()
            pack_names = [p["name"] for p in packs]
            assert "hello_pack" not in pack_names, \
                f"hello_pack should not be in pack list after removal: {pack_names}"

            # 6. Verify capability no longer in database
            caps_after = list_capabilities()
            cap_names_after = [c.get("name", "") for c in caps_after if isinstance(c, dict)]
            assert "hello_pack.hello" not in cap_names_after, \
                f"hello_pack.hello should NOT be in capabilities after removal: {cap_names_after}"

            # 7. Verify no stale entries (by exact name lookup)
            from remote_terminal.nous_core.capability import get_capability
            assert get_capability("hello_pack.hello") is None, \
                "get_capability('hello_pack.hello') should return None after removal"

        finally:
            reg_module.PACK_REGISTRY_FILE = old_reg_file

    def test_unregister_capability_direct(self):
        """unregister_capability() works correctly at the DB level."""
        from remote_terminal.nous_core.capability import (
            register_capability,
            unregister_capability,
            get_capability,
        )

        # Register a test capability
        cid = register_capability(
            "test.unregister.direct",
            category="pack",
            provider="test_provider_direct",
            description="Test capability for unregister",
        )
        assert cid, "register_capability should return an ID"

        # Verify it exists
        assert get_capability("test.unregister.direct") is not None

        # Unregister it
        ok = unregister_capability("test.unregister.direct")
        assert ok, "unregister_capability should return True"

        # Verify it's gone
        assert get_capability("test.unregister.direct") is None

    def test_unregister_nonexistent_returns_false(self):
        """unregister_capability() on a nonexistent cap returns False."""
        from remote_terminal.nous_core.capability import unregister_capability
        ok = unregister_capability("nonexistent.capability.xyz")
        assert ok is False

    def test_unregister_capabilities_by_provider(self):
        """unregister_capabilities_by_provider() removes all caps for a provider."""
        from remote_terminal.nous_core.capability import (
            register_capability,
            unregister_capabilities_by_provider,
            list_capabilities,
        )

        PROVIDER = "test_bulk_provider"

        # Register multiple capabilities under the same provider
        for i in range(3):
            register_capability(
                f"test.bulk.{i}",
                category="pack",
                provider=PROVIDER,
                description=f"Bulk test capability {i}",
            )

        # Verify they exist
        caps_before = list_capabilities()
        bulk_names = [
            c.get("name") for c in caps_before
            if isinstance(c, dict) and c.get("provider") == PROVIDER
        ]
        assert len(bulk_names) == 3, f"Expected 3 caps, got: {bulk_names}"

        # Bulk-remove by provider
        removed = unregister_capabilities_by_provider(PROVIDER)
        assert removed == 3, f"Expected 3 removed, got {removed}"

        # Verify all gone
        caps_after = list_capabilities()
        remaining = [
            c.get("name") for c in caps_after
            if isinstance(c, dict) and c.get("provider") == PROVIDER
        ]
        assert len(remaining) == 0, \
            f"Expected 0 caps for provider {PROVIDER}, got: {remaining}"
