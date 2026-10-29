# FAQ / 常见问题

## Is APEIR a model?

No. APEIR is the platform. Studio is the workspace, Runtime governs execution,
and Kernel is the pinned controlled-execution component. Models and external
Agents supply intelligence; they cannot approve their own operations.

## Can local models and cloud APIs coexist?

Yes, supported adapters can be configured together with separate Provider/model
identities. You still need a running local service or valid cloud account, the
actual supported protocol and the authenticated Kernel. A catalog entry alone
does not prove inference. See [Models and Providers](guides/PROVIDER_GUIDE.md).

## Does Chat stream progress?

Chat displays recorded model/tool events, approval waits and failures while a
request runs. The current frozen NKI returns complete model responses; production
token-by-token text streaming is not available. Event disconnection does not
mean the backend task stopped. See [activity details](../development/DEVELOPER_PLATFORM.md#watching-a-request).

## Can every Skill or plugin execute tools?

No. Instruction Skills supply text. Reviewed declarative UI extensions supply
panels/widgets. Executable tools need a real supported implementation and current
permission. Installation does not grant either.
See [Skills](../development/DEVELOPER_PLATFORM.md#skills-and-tools) and
[UI extensions](../development/DEVELOPER_PLATFORM.md#declarative-ui-extension-sdk).

## Does APEIR reduce Token cost?

Bounded context selection, deterministic reads and restrained collaboration can
avoid unnecessary work. Actual usage remains visible in the original accounting
journal. There is no demonstrated general saving percentage; missing usage or
price stays UNKNOWN. See [usage and cost](../development/DEVELOPER_PLATFORM.md#model-usage-and-cost).

## Where are credentials stored?

Saved profiles retain references. Values resolve from the configured environment
or secure credential backend. Native local settings use the existing system
store; browser Studio cannot save Provider keys. Do not put keys in layouts,
ordinary logs or screenshots.

## Why is a test BLOCKED after a file change succeeded?

File readback and test execution are separate Gates. A supported command still
needs its current permission, toolchain and qualified strict sandbox. An
unrestricted host Shell is not a fallback. File SHA-256 MATCH is not test PASS.

## Should I resubmit after losing a response?

Inspect the original Work/Run first. It may already have executed or incurred
model cost. Recovery reconciles its original records; it must not blindly repeat
an uncertain effect.

## Where is the Windows installer?

[Quick Start](getting-started/QUICK_START.md#native-installation) links the current
unsigned x64 test bundle and checksums. It contains Portable and NSIS packages;
Windows10 installed lifecycle and signing remain separate, unqualified Gates.
Source Preview is not an EXE.

## Is SHA-256 verification the same as Windows signing or installation testing?

No. SHA-256 checks whether the downloaded file matches the build record.
Authenticode identifies a signing publisher; the current preview is unsigned.
Installation acceptance requires actually installing and running the package on
Windows 10. One result cannot replace either of the others. Do not disable
Defender or treat a matching hash as a security certification.

## Are clients authoritative?

No. Studio, CLI and external clients read and request actions through existing
Runtime services. Governance retains authorization. A status card, receipt or
model response cannot substitute for an independent effect observation.
