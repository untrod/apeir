"""Install, discover and load instructions through the public Skill facade."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from nous_provider.runtime import (
    ContentAddressedArtifactStore,
    SkillRegistry,
    SkillToolRuntime,
)


def run(root: Path, source: Path) -> dict:
    registry = SkillRegistry(root)
    record = registry.install(source)
    tools = SkillToolRuntime(root)
    loaded = tools.execute("skill_load", {"skill_id": "installed:" + record.skill_id})
    cas = ContentAddressedArtifactStore(root / ".nous" / "artifacts")
    if not cas.verify(record.artifact_ref):
        raise ValueError("Installed Skill evidence failed integrity validation")
    mutation = tools.execute("skill_install", {"source": str(source)})
    unknown = tools.execute("device.firmware.update", {})
    registry.disable(record.skill_id)
    disabled = SkillToolRuntime(root).execute(
        "skill_load", {"skill_id": "installed:" + record.skill_id}
    )
    return {
        "workspace": str(root),
        "record": record.to_dict(),
        "loaded": loaded,
        "artifact_integrity": True,
        "agent_install_denied": mutation,
        "operation_not_executable_as_skill": unknown,
        "disabled_after_reopen": disabled,
        "authority": "none",
        "execution_performed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    root = args.workspace or Path(tempfile.mkdtemp(prefix="apeir-hello-skill-"))
    if root.exists() and any(root.iterdir()):
        parser.error("Use an empty dedicated workspace; preserve prior evidence")
    root.mkdir(parents=True, exist_ok=True)
    print(
        json.dumps(
            run(root.resolve(), Path(__file__).parent / "verified-device-review"),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
