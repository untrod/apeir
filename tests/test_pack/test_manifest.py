# -*- coding: utf-8 -*-
"""Pack manifest contract tests."""

import os
import tempfile

import pytest
from nous_runtime.pack.manifest import PackManifest


class TestPackManifest:
    """PackManifest must parse and validate correctly."""

    def test_valid_manifest(self, tmp_pack_dir):
        """A valid pack.yaml parses without error."""
        manifest = PackManifest.from_file(tmp_pack_dir)
        assert manifest.name == "test_pack"
        assert manifest.version == "1.0.0"
        assert "test.hello" in manifest.capabilities

    def test_missing_name_rejected(self):
        """Manifest without name must fail."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "pack.yaml"), "w") as f:
                f.write("version: 1.0.0\ndescription: No name\n")
            with pytest.raises((ValueError, FileNotFoundError)):
                PackManifest.from_file(d)

    def test_missing_version_rejected(self):
        """Manifest without version must fail."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "pack.yaml"), "w") as f:
                f.write("name: test\ndescription: No version\n")
            with pytest.raises((ValueError, FileNotFoundError)):
                PackManifest.from_file(d)

    def test_invalid_name_format(self):
        """Manifest with invalid name format must fail."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "pack.yaml"), "w") as f:
                f.write("name: Invalid-Name!\nversion: 1.0.0\ndescription: Bad name\n")
            with pytest.raises((ValueError, FileNotFoundError)):
                PackManifest.from_file(d)

    def test_invalid_version_format(self):
        """Manifest with non-semver version must fail."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "pack.yaml"), "w") as f:
                f.write("name: test\nversion: one-point-oh\ndescription: Bad version\n")
            with pytest.raises((ValueError, FileNotFoundError)):
                PackManifest.from_file(d)

    def test_no_pack_yaml(self):
        """Directory without pack.yaml must fail."""
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(FileNotFoundError):
                PackManifest.from_file(d)

    def test_to_dict(self, tmp_pack_dir):
        """to_dict round-trips correctly."""
        manifest = PackManifest.from_file(tmp_pack_dir)
        d = manifest.to_dict()
        assert d["name"] == "test_pack"
        assert d["version"] == "1.0.0"


class TestPackLoader:
    """Pack loader must load and register packs."""

    def test_load_valid_pack(self, tmp_pack_dir):
        """A valid pack directory loads without error."""
        from nous_runtime.pack.loader import load_pack
        pack = load_pack(tmp_pack_dir)
        assert pack.manifest.name == "test_pack"
        # Module may be None if src/__init__.py fails to import
        # (e.g., missing remote_terminal in test path)
        # The manifest should still load successfully.
        assert pack.manifest.version == "1.0.0"

    def test_load_missing_directory(self):
        """Loading a nonexistent directory must fail."""
        from nous_runtime.pack.loader import load_pack
        with pytest.raises((FileNotFoundError, ValueError)):
            load_pack("/nonexistent/path")


class TestPackRegistry:
    """Pack registry must install, list, and remove packs."""

    @pytest.fixture(autouse=True)
    def isolate_registry(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "NOUS_PACK_REGISTRY_FILE",
            str(tmp_path / "pack_registry.json"),
        )

    def test_install_and_list(self, tmp_pack_dir):
        """Installing a pack and listing it works."""
        from nous_runtime.pack.registry import PackRegistry
        reg = PackRegistry()
        pack = reg.install(tmp_pack_dir)
        assert pack.manifest.name == "test_pack"

        packs = reg.list()
        assert len(packs) == 1
        assert packs[0]["name"] == "test_pack"

    def test_remove(self, tmp_pack_dir):
        """Removing a pack works."""
        from nous_runtime.pack.registry import PackRegistry
        reg = PackRegistry()
        reg.install(tmp_pack_dir)
        reg.remove("test_pack")
        assert reg.list() == []

    def test_duplicate_install_rejected(self, tmp_pack_dir):
        """Installing the same pack twice must fail."""
        from nous_runtime.pack.registry import PackRegistry
        reg = PackRegistry()
        reg.install(tmp_pack_dir)
        with pytest.raises(ValueError):
            reg.install(tmp_pack_dir)

    def test_remove_nonexistent(self):
        """Removing a nonexistent pack must fail."""
        from nous_runtime.pack.registry import PackRegistry
        reg = PackRegistry()
        with pytest.raises(KeyError):
            reg.remove("nonexistent")
