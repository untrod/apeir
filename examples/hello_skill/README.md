# Hello Skill

This example uses the public SDK facade over the existing SkillRegistry and
SkillToolRuntime. Follow the [Source Quick Start](../../docs/operations/getting-started/QUICK_START.md#public-sdk-examples), then run from the checkout:

```bash
python examples/hello_skill/run_example.py --workspace ./skill-demo
```

The local CLI user registers the reviewed example directory and installs its
exact catalog version and content digest into an empty dedicated workspace.
The Registry discovers its declared high risk and
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

## Desktop Skill Center

The existing Operations Console exposes the workspace's canonical Skills alongside
Work, Nodes, Approvals and Evidence. Register a reviewed local catalog as the
workspace owner before opening the UI:

```bash
apeir skill catalog add /absolute/path/to/apeir/examples/hello_skill --root /absolute/path/to/workspace
apeir skill list --root /absolute/path/to/workspace --include-disabled --json
```

Connect the Console to that workspace's existing Runtime API, using the
[Quick Start](../../docs/operations/getting-started/QUICK_START.md) and existing
trusted human-session configuration. A service bearer token is observe-only for
these controls. The human needs `governance.approve` plus `control.skill_install`,
`control.skill_manage` or `control.skill_load` on `skill:<skill_id>` as applicable;
permission configuration is a trusted-host responsibility, never a UI action.

Open **Skills**, search records, choose **Review package**, inspect source, version,
digest, risk, requested capabilities and compatibility, then confirm that exact
entry and **Install reviewed package**. Select the installed entry to inspect CAS
evidence, **Load instructions**, **Disable**, **Enable** or **Uninstall**. Loading
reads instructions only. The separate [Verified Demo](../hello_runtime/README.md)
exercises the proposed device action through existing Work and Governance.

Catalog changes after review require reviewing again. Sources cannot escape the
registered local catalog directory. Archive limits and Extension inspection apply
before publication; CAS failures and failed index publication preserve the prior
valid installation. Disabled state survives updates and restart. Revoked installed
Skills cannot be restored by reinstalling through the Catalog.

This example qualifies local catalog management and source-browser controls.
The existing [reviewed HTTPS catalog path](../../docs/architecture/SECURITY_CONTRACT.md#skillextension-acquisition-before-publication)
separately exercises controlled remote acquisition, including owned HTTP/TLS
integration tests. It does not qualify arbitrary publishers or executable Skill
workflows. Passive Console refresh does not fetch remote catalogs. Real IdP,
installed Windows Desktop and physical execution retain their separate
qualification gates. A hard crash between
Extension index and lock publication fails closed; this is not a multi-file crash
transaction. Staged CAS evidence can remain pinned after failed publication for
inspection; no automatic deletion of failure evidence is introduced.
