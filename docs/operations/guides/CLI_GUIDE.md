# APEIR CLI Guide

## Overview

The [CLI reference](../../development/CLI_REFERENCE.md) owns current command
syntax. Use `apeir --help` or `apeir GROUP --help` for your installed version;
`nous` remains a compatibility alias.

## Global Commands

[Quick Start](../getting-started/QUICK_START.md) covers installation, the
foreground `runtime-api start` command and connecting Studio. There is no
current `apeir start` shortcut.

## Capability

Use `apeir --no-intelligence capability availability` for the current projection.
Availability is not permission; [interpret its scope](../CAPABILITY_AVAILABILITY.md)
before requesting an operation. Old `capability run` examples are not supported
by the current CLI.

## Provider

Follow [Models and Providers](PROVIDER_GUIDE.md). A reachability probe and a
potentially billed inference test are different operations.

## Pack

See the [Pack guide](PACK_GUIDE.md); installation alone does not run a capability.

## Execution

Start with [Hello Workflow](../../../examples/hello_workflow/README.md) or the
[Verified Execution Demo](../../../examples/hello_runtime/README.md). Keep the
original Run and idempotency key when inspecting or recovering.

## Developer

[Developer Setup](../getting-started/QUICK_START.md#developer-setup),
[public examples](../../../examples/README.md) and
[CONTRIBUTING](../../../CONTRIBUTING.md) are the supported entry points.

## Interactive Shell Slash Commands

`apeir chat` starts the existing interactive surface. Its current `/help` is the
source for slash commands. Inference needs its actual model and Kernel; source
browsing and pure Workflow examples do not need a model account.

## Shell Tips

Stop a foreground service with its normal interrupt and inspect cleanup. Stopping
an HTTP wait or closing a panel does not confirm that an admitted task stopped.
Do not resubmit an uncertain effect to obtain a fresh status message.
