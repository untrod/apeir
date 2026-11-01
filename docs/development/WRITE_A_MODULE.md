# Write a Module

Choose an existing public extension boundary before adding Core code. Most
integrations do not need a Runtime module.

| Goal | Supported starting point |
| --- | --- |
| Add a read-only panel or Widget | [UI Extension SDK](STUDIO_UI_EXTENSIONS.md) |
| Supply a tool/model/device adapter | [Provider SDK](PROVIDER_DEVELOPMENT.md) and [Hello Provider](../../examples/hello_provider/README.md) |
| Supply reviewable instructions | [Hello Skill](../../examples/hello_skill/README.md) |
| Package reviewed domain data | [Pack development](PACK_DEVELOPMENT.md) |

## Module Manifest

Use the versioned manifest for the chosen extension kind. Manifest permission
requests do not become grants. There is no generic JSON file that authorizes a
new module to access the host.

## Module Class

Core modules follow the existing owners in the
[Runtime module map](RUNTIME_MODULE_MAP.md). They are implementation details,
not an unrestricted third-party lifecycle API.

## Registration

New integrations use the existing host/Registry appropriate to their kind.
Do not import the old `nous_core.security.register_module_permissions` sketch
as a public authority API. Core changes require the normal architecture and
PR process in [CONTRIBUTING](../../CONTRIBUTING.md); Kernel remains frozen.

## Isolation Rules

An imported Python module is not automatically sandboxed. Use the qualified
execution environment for untrusted code, current resource permissions and the
canonical execution path. Missing isolation stays BLOCKED; installing an
extension does not supply it.
