"""Shared legacy-compatible node state location for all command entry points."""

from pathlib import Path

# Keep existing node identities discoverable during the additive brand transition.
DEFAULT_NODE_STATE_DIR = Path(".nous") / "node"
