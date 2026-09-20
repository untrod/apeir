# -*- coding: utf-8 -*-
"""Freeze unmanaged network egress while protocol-specific paths migrate."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from nous_runtime.network.egress import (
    AUTHORITIES,
    DIRECT_CALL_BASELINE,
    validate_egress_contracts,
)


ROOT = Path(__file__).resolve().parents[2]
DIRECT_OPEN = re.compile(
    r"(?:urllib\.request\.urlopen|(?<![\w.])urlopen|_ur\.urlopen|"
    r"_no_proxy\.open|requests\.(?:get|post|put|delete|request)|"
    r"httpx\.(?:get|post|put|delete|request))\s*\("
)
BASELINE = DIRECT_CALL_BASELINE


def test_unmanaged_network_egress_baseline_cannot_grow() -> None:
    observed: Counter[str] = Counter()
    for top_level in ("nous_runtime", "remote_terminal"):
        for path in (ROOT / top_level).rglob("*.py"):
            relative = path.relative_to(ROOT).as_posix()
            if relative == "nous_runtime/runtime/audit.py":
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            count = len(DIRECT_OPEN.findall(content))
            if count:
                observed[relative] = count

    assert dict(observed) == BASELINE
    assert sum(observed.values()) == 19
    assert validate_egress_contracts() == []
    assert AUTHORITIES["research.public_web"].private_targets_allowed is False
    assert AUTHORITIES["device.agent"].private_targets_allowed is True

    migrated_device_paths = (
        "remote_terminal/brain.py",
        "remote_terminal/brain_devices.py",
        "remote_terminal/brain_utils.py",
        "remote_terminal/tools.py",
    )
    for relative in migrated_device_paths:
        content = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        assert not DIRECT_OPEN.search(content)
        assert "device_transport" in content

    authority = (ROOT / "remote_terminal/device_transport.py").read_text(encoding="utf-8")
    assert "ProxyHandler({})" in authority
    assert "_NoRedirect" in authority
    assert "max_response_bytes" in authority