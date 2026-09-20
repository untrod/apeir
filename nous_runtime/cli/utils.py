# -*- coding: utf-8 -*-
"""CLI formatting helpers."""

from __future__ import annotations


def fmt_table(headers: list[str], rows: list[list[str]], padding: int = 2) -> str:
    """Format data as an aligned text table."""
    if not rows:
        return ""

    col_widths = [
        max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
        for i, h in enumerate(headers)
    ]

    lines = []
    header_line = "".join(f"{h:<{w + padding}}" for h, w in zip(headers, col_widths))
    lines.append(header_line)
    lines.append("-" * len(header_line))

    for row in rows:
        lines.append("".join(f"{str(c):<{w + padding}}" for c, w in zip(row, col_widths)))

    return "\n".join(lines)


def fmt_status_icon(status: str) -> str:
    """Return a portable text marker for a status string."""
    markers = {
        "ok": "[OK]",
        "degraded": "[WARN]",
        "down": "[FAIL]",
        "unknown": "[?]",
    }
    return markers.get(status, "[?]")
