from __future__ import annotations

from pathlib import Path
import json
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_apeir_commands_are_added_without_removing_nous_aliases() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]
    gui_scripts = project["project"]["gui-scripts"]

    assert scripts["apeir"] == scripts["nous"]
    assert scripts["apeir-node"] == scripts["nous-node"]
    assert scripts["apeir-relay"] == scripts["nous-relay"]
    assert gui_scripts["apeir-installer"] == gui_scripts["nous-installer"]


def test_brand_transition_does_not_relabel_v1_protocols() -> None:
    # The Distribution must test independently of a sibling Kernel checkout.
    from nous_runtime.node_runtime.protocol import NODE_PROTOCOL, NODE_PROTOCOL_VERSION
    from nous_runtime.node_runtime.paths import DEFAULT_NODE_STATE_DIR

    assert NODE_PROTOCOL == "nous-node"
    assert NODE_PROTOCOL_VERSION == "1.0"
    assert DEFAULT_NODE_STATE_DIR == Path(".nous") / "node"


def test_distribution_lock_names_apeir_without_changing_component_identity() -> None:
    lock = json.loads(
        (ROOT / "runtime-components.lock.json").read_text(encoding="utf-8")
    )
    component = lock["components"]["nous-kernel"]

    assert lock["brand"]["canonical"] == "APEIR"
    assert component["canonical_name"] == "apeir-kernel"
    assert component["component_id"] == "nous-kernel"
    assert component["protocol"] == "nous.nki.v1"
    assert len(component["revision"]) == 40
