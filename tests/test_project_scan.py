# -*- coding: utf-8 -*-
"""Project scan tests — file indexing."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestScanProject:
    def test_scan_empty_dir(self, tmp_path):
        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        summary = scan_project(tmp_path)
        assert isinstance(summary, dict)
        assert "total_files" in summary
        # .nous/ files are excluded; empty dir may have 0 files
        assert summary["total_files"] >= 0

    def test_scan_excludes_git(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]")
        (tmp_path / "README.md").write_text("# Hello")

        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        scan_project(tmp_path)

        # Should find README.md but NOT .git/config
        index_path = tmp_path / ".nous" / "index" / "files.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        paths = [f["path"] for f in data]
        assert "README.md" in paths
        assert not any(p.startswith(".git") for p in paths)

    def test_scan_excludes_nous(self, tmp_path):
        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        # Add a test file outside .nous
        (tmp_path / "main.py").write_text("print('hi')")

        scan_project(tmp_path)
        index_path = tmp_path / ".nous" / "index" / "files.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        paths = [f["path"] for f in data]
        # main.py should be indexed, .nous files should not
        assert "main.py" in paths
        assert not any(".nous" in p for p in paths)

    def test_scan_excludes_common_dirs(self, tmp_path):
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        (tmp_path / "node_modules" / "pkg" / "index.js").write_text("// x")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "build").mkdir()
        (tmp_path / "dist").mkdir()
        (tmp_path / ".venv").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("x=1")

        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        scan_project(tmp_path)

        index_path = tmp_path / ".nous" / "index" / "files.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        paths = [f["path"] for f in data]
        assert "src/app.py" in paths
        assert not any(p.startswith("node_modules") for p in paths)
        assert not any(p.startswith("__pycache__") for p in paths)
        assert not any(p.startswith("build") for p in paths)
        assert not any(p.startswith(".venv") for p in paths)

    def test_scan_output_structure(self, tmp_path):
        (tmp_path / "README.md").write_text("# Test")
        (tmp_path / "main.py").write_text("print('hi')")

        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        scan_project(tmp_path)

        index_path = tmp_path / ".nous" / "index" / "files.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))

        for entry in data:
            assert "path" in entry
            assert "type" in entry
            assert "size" in entry
            assert "modified" in entry
            assert isinstance(entry["size"], int)
            assert isinstance(entry["path"], str)

    def test_scan_summary_has_types(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        (tmp_path / "README.md").write_text("# hi")
        (tmp_path / "config.json").write_text("{}")

        from nous_runtime.project.scan import scan_project
        from nous_runtime.project.workspace import init_workspace

        init_workspace(tmp_path)
        summary = scan_project(tmp_path)

        assert "types" in summary
        assert isinstance(summary["types"], dict)
        assert "total_size_kb" in summary
        assert "scanned_at" in summary
