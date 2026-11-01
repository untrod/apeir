# APEIR CLI reference

Use `apeir --help` and `apeir GROUP --help` for the installed version. The
`nous` alias and some help text keep historical compatibility names. The current
Distribution is `0.1.0-rc1`; a protocol/schema version is not a package release.

## Global Commands

```bash
apeir version
apeir --help
apeir --no-intelligence status
apeir --no-intelligence doctor
```

Use `--no-intelligence` for model-free inspection. It disables model calls for
that process; it does not remove saved profiles. `apeir init --help` describes
the optional workspace initializer. The recommended first start is:

```bash
apeir --no-intelligence runtime-api start
```

This stays in the foreground. In a second terminal, from the same workspace:

```bash
apeir runtime-api status --json
apeir runtime-api token-path
```

`token-path` is an existing hidden trusted-desktop command: it prints the local
protected session file's path, not its value. Follow
[connection setup](../operations/getting-started/QUICK_START.md#model-free-runtime-api-and-source-interface).
There is no current `apeir start` command.

## Capability

```bash
apeir --no-intelligence capability list
apeir --no-intelligence capability availability
```

These inspect metadata. `capability run` is not a current CLI subcommand.
Use an existing governed Work/Workflow or supported application operation;
[availability](../operations/CAPABILITY_AVAILABILITY.md) is not permission.

## Provider

```bash
apeir --no-intelligence provider list
apeir --no-intelligence provider show PROVIDER_ID
apeir --no-intelligence provider status
apeir --no-intelligence provider doctor
```

`provider add` opens the existing configuration wizard. `provider ping` is a
reachability check; `provider test` sends a model request and can incur cost.
Use the [Provider guide](../operations/guides/PROVIDER_GUIDE.md), explicit account
and budget authorization, and the authenticated Kernel. A model-disabled process
cannot infer.

## Pack

```bash
apeir --no-intelligence pack list
apeir pack --help
```

Local package management and capability execution are separate. See the
[Pack guide](../operations/guides/PACK_GUIDE.md) before installing trusted code.
No public Pack publishing service is qualified by this preview.

## Execution

```bash
apeir --no-intelligence workflow validate workflow.json --json
apeir --no-intelligence workflow register workflow.json --json
apeir --no-intelligence workflow run WORKFLOW_ID --idempotency-key first --json
apeir --no-intelligence workflow show RUN_ID --json
```

Use actual IDs returned by the original operation. Supported pure steps need no
model; other hosts have their own prerequisites. See
[Hello Workflow](../../examples/hello_workflow/README.md). `work --help` lists
original Work inspection, pause, cancel and recovery commands. Never infer retry
safety from a lost response.

For an original pending approval in the owning workspace:

```bash
apeir --no-intelligence approval show APPROVAL_ID --json
apeir --no-intelligence approval approve APPROVAL_ID
```

This is an independent local human decision, not a service token approving its
own request. Model/command/device effects retain their existing admission rules.

## Developer

[Developer Setup](../operations/getting-started/QUICK_START.md#developer-setup)
owns installation commands. [CONTRIBUTING](../../CONTRIBUTING.md) owns checks and
PR policy. Start extensions from [tested examples](../../examples/README.md),
not old `nous_core` registration snippets or unqualified scaffold assumptions.
