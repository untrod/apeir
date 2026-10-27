"""The frozen sidecar must retain the existing public dynamic CLI families."""

import ast
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_spec_discovers_existing_command_table_without_importing_runtime(monkeypatch):
    captured = {}
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda *_args, **_kwargs: []
    hooks.copy_metadata = lambda *_args, **_kwargs: []
    for name in ("PyInstaller", "PyInstaller.utils"):
        package = ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)

    def analysis(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    before = set(sys.modules)
    result = runpy.run_path(
        str(ROOT / "nous-sidecar.spec"),
        init_globals={
            "SPECPATH": str(ROOT),
            "Analysis": analysis,
            "PYZ": lambda *_: None,
            "EXE": lambda *_args, **_kwargs: None,
        },
    )
    source = (ROOT / "nous_runtime/cli/main.py").read_text(encoding="utf-8")
    declaration = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Tuple)
        and [getattr(item, "id", None) for item in node.target.elts]
        == ["_module_name", "_register_name"]
    )
    expected = [module for module, _register in ast.literal_eval(declaration.iter)]
    assert "nous_runtime.workflow.cli" in captured["hiddenimports"]
    assert set(expected) <= set(captured["hiddenimports"])
    assert len(expected) == len(set(expected))
    assert not [
        name for name in set(sys.modules) - before if name.startswith("nous_runtime.")
    ]
    assert {"numpy", "torch", "faster_whisper"} <= set(captured["excludes"])
    assert result["_command_modules"](source) == expected
    discovery = result["_command_modules"]
    static_table = (
        "for _module_name, _register_name in "
        "(('nous_runtime.workflow.cli', 'register_workflow_commands'),):\n    pass\n"
    )
    assert discovery(
        "raise RuntimeError('must not execute CLI source')\n" + static_table
    ) == ["nous_runtime.workflow.cli"]
    for invalid in (
        "pass",
        "for _module_name, _register_name in untrusted_call():\n    pass",
        "for _module_name, _register_name in (('os', 'system'),):\n    pass",
        static_table + static_table,
    ):
        with pytest.raises(ValueError):
            discovery(invalid)
