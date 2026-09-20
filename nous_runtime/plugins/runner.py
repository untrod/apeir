"""Subprocess entry point for local Plugin invocation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        package = Path(request["package"]).resolve()
        sys.path.insert(0, str(package))
        module_name, function_name = str(request["entry_point"]).split(":", 1)
        function = getattr(importlib.import_module(module_name), function_name)
        result = function(str(request["capability"]), dict(request.get("payload") or {}))
        sys.stdout.write(json.dumps({"ok": True, "result": result or {}}, ensure_ascii=False))
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())