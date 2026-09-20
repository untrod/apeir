# Project Runtime — .nous/ Workspace

## What is .nous/?

`.nous/` is the project-level data directory for Nous Runtime.  It lives
in your project root and holds everything the Runtime knows about your
project: configuration, goals, tasks, memory, file index, execution
traces, and generated artifacts.

## Directory Structure

```
.nous/
├── project.json          # project metadata (name, root, created)
├── config.json           # project-level config overrides
├── goals.json            # project goals
├── tasks.json            # project task list
├── history               # shell command history (plain text)
├── memory/
│   ├── timeline.jsonl    # chronological event log
│   ├── decisions.jsonl   # user-confirmed decisions
│   ├── summaries.jsonl   # periodic stage summaries
│   └── facts.jsonl       # stable project facts
├── index/
│   └── files.json        # project file index (from /scan)
├── traces/               # execution traces
└── artifacts/            # generated assets
```

## How It Works

### Auto-detection

When you run `nous` with no arguments, Nous walks up from the current
directory looking for a `.nous/` folder.  If found, it uses that
workspace.  If not found, it prompts:

```
No Nous workspace found.
Create .nous for this project? [Y/n]
```

Answer `y` (or press Enter) to create one.  Answer `n` to skip —
you can run `nous project init` later.

### Manual Creation

```bash
nous project init          # create in current directory
nous project init --path /path/to/project
```

### Project Scan

```bash
nous project scan          # index files into .nous/index/files.json
```

Or from the shell: `/scan`

## Data Privacy

**All data stays on your machine.**  The `.nous/` directory is a local
folder — nothing is uploaded, synced, or shared.  Add `.nous/` to your
`.gitignore` if you don't want to commit it.

```gitignore
# Nous Runtime workspace
.nous/
```

## Lifecycle

1. **Create** — `nous project init` or auto-prompt
2. **Use** — every `nous` shell session reads/writes to `.nous/`
3. **Delete** — `rm -rf .nous` removes everything (no side effects)
