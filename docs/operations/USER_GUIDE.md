# User Guide

## First checks

```powershell
nous doctor
nous status
nous models doctor
```

`nous doctor` reports the Runtime version, workspace, optional dependencies,
provider availability, and foundation health. Warnings about optional packages
or missing provider keys do not prevent the built-in demo from running.

## Workspaces

Initialize the current directory:

```powershell
nous init --path .
```

Runtime state is stored under `.nous/` and is excluded from Git. Back up the
workspace before migrations or destructive maintenance.

## Providers and models

```powershell
nous provider list
nous provider add
nous provider status
nous provider doctor
nous models list
nous models doctor
nous models configure
```

Use credential references or environment variables. Do not paste credentials
into public logs, screenshots, configuration examples, or issue reports.

## Tasks and interaction

```powershell
nous demo
nous chat
nous task list
nous trace
```

The task owner records lifecycle state, checkpoints, artifacts, events, and
verification results. Clients display that state rather than maintaining a
second task database.

## Local Control Plane

```powershell
nous server init --host 127.0.0.1 --port 9770
nous server start
```

Keep the service bound to localhost for a single-device deployment. Remote
access requires authentication, TLS termination, firewall rules, and an
explicit threat review.

## Troubleshooting

1. Activate the intended virtual environment.
2. Run `where.exe nous` and `python --version`.
3. Run the three diagnostic commands at the top of this guide.
4. Review the [troubleshooting guide](getting-started/TROUBLESHOOTING.md).
5. Report reproducible non-security issues with redacted diagnostics.