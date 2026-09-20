"""Unified-diff scope validation."""

from __future__ import annotations

from pathlib import PurePosixPath


class PatchScopeError(ValueError):
    pass


def changed_paths_from_diff(text: str) -> tuple[str, ...]:
    paths: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("+++ "):
            continue
        value = line[4:].split("\t", 1)[0]
        if value == "/dev/null":
            continue
        if value.startswith("b/"):
            value = value[2:]
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise PatchScopeError("patch path escapes workspace")
        paths.add(path.as_posix())
    return tuple(sorted(paths))


def validate_diff_scope(text: str, allowed_files: tuple[str, ...]) -> tuple[str, ...]:
    changed = changed_paths_from_diff(text)
    allowed = {PurePosixPath(item.replace("\\", "/")).as_posix() for item in allowed_files}
    denied = set(changed) - allowed
    if denied:
        raise PatchScopeError("patch modifies files outside approved scope: " + ", ".join(sorted(denied)))
    return changed