# Hello Skill

This example uses the public SDK facade over the existing SkillRegistry and
SkillToolRuntime. Follow the [Source Quick Start](../../docs/operations/getting-started/QUICK_START.md#public-sdk-examples), then run from the checkout:

```bash
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

The local CLI user explicitly installs `verified-device-review/SKILL.md` into an
empty dedicated workspace. The Registry discovers its declared high risk and
requested device capabilities, records provenance and stores the bundle in the
existing Artifact CAS. The tool loads the actual instructions and verifies the
stored artifact; it then denies agent-driven installation and device execution
through a Skill tool. Finally, disable is persisted and loading after reopening
fails. JSON shows those actual results and the installed record.

Loading instructions is the result of this example. No device operation or
script executes. Requested capabilities are not permissions, installation is
not trust, and a Skill has no authority. To execute the instructions' proposed
operation, use the existing governed [Verified Demo](../hello_runtime/README.md).
Do not introduce an executor or approval mechanism inside a Skill.

Keep the printed workspace for local inspection; do not publish Runtime state.
