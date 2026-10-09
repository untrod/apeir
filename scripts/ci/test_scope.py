"""Conservative PR test selection; main/release/dispatch always use full CI."""

from __future__ import annotations

import argparse
import os
from pathlib import PurePosixPath
import subprocess

ROOT_DOCS = frozenset(
    {
        "README.md",
        "README.zh-CN.md",
        "ROADMAP.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CHANGELOG.md",
    }
)
EXAMPLE_DOCS = frozenset(
    {
        "examples/README.md",
        "examples/hello_runtime/README.md",
        "examples/hello_provider/README.md",
        "examples/hello_skill/README.md",
        "examples/hello_workflow/README.md",
    }
)


def classify(paths: list[str], *, event: str) -> str:
    if event != "pull_request" or not paths:
        return "full"
    for path in paths:
        parts = PurePosixPath(path).parts
        if path.startswith("/") or ".." in parts or "\\" in path:
            return "full"
        if not (
            path in ROOT_DOCS
            or path in EXAMPLE_DOCS
            or path.startswith("docs/")
            and path.endswith(".md")
        ):
            return "full"
    return "documentation"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    base = os.environ.get("BASE_SHA", "")
    if not base or set(base) == {"0"}:
        base = "HEAD^"
    parser.add_argument("--base", default=base)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--event", default=os.environ.get("EVENT_NAME", "push"))
    args = parser.parse_args()
    # Every changed path participates, including deleted files and both rename
    # ends. A missing Git object or invalid revision is a failure, never docs-only.
    for revision in (args.base, args.head):
        if not revision or revision.startswith("-"):
            parser.error("base/head must be explicit Git revisions")
    paths = (
        subprocess.check_output(
            [
                "git",
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                args.base,
                args.head,
                "--",
            ]
        )
        .decode()
        .strip("\0")
        .split("\0")
    )
    scope = classify(paths, event=args.event)
    print(scope)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"scope={scope}\n")


if __name__ == "__main__":
    main()
