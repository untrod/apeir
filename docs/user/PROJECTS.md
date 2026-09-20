# Project Workspaces

A Nous project is a normal directory with Runtime metadata under `.nous/`.
Source files remain owned by the user and can continue to use ordinary Git
workflows.

## Create or open a project

```powershell
cd path\to\project
nous init --path .
nous status
```

## Workspace responsibilities

- Project source and documentation remain in the project tree.
- Runtime state, sessions, checkpoints, and local indexes remain under `.nous/`.
- Credentials remain in environment variables or the credential provider.
- Generated artifacts should use explicit project output directories.
- `.nous/`, databases, caches, and private logs must not be committed.

## Common commands

```powershell
nous project --help
nous task list
nous memory --help
nous retrieval --help
nous inspect --help
```

Back up project data before changing storage schemas or moving a long-running
workspace between devices.