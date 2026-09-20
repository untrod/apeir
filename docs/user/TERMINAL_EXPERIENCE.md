# Terminal Experience — Nous Runtime Shell

## Design Philosophy

The Runtime terminal is designed for **clarity, density, and long-term
daily use**.  It should communicate *"this is your operating environment"*
rather than *"this is a Python CLI tool."*

Every pixel earns its place.  The dashboard fades into the background
after a few minutes — the user focuses on their work, not the UI.

References: fastfetch, neofetch and established interactive developer CLIs.

## Runtime Entry

```
nous
```

1. **Loading sequence** — brief transition (no delays, no spinners)
2. **Workspace detection** — finds or creates `.nous/`
3. **Dashboard** — compact project status
4. **Session summary** — last session recap
5. **Prompt** — `nous >`

## Adaptive Dashboard Layout

The dashboard adapts to terminal width automatically:

| Width     | Layout                             |
|-----------|------------------------------------|
| ≥ 90 cols | Side-by-side (logo left, status right) |
| 60–89     | Stacked (logo above, status below) |
| < 60      | Minimal (label only, no logo)      |

### Status Fields

```
Runtime        v1.1-dev
Project        Agent_play
Workspace      .nous
Mode           interactive

Providers      2 configured
Capabilities   27 available

Memory         Ready
Timeline       42 events

Tasks          3 running
Queue          0 pending

Path           <workspace>
Started        14:36
```

### Logos

- **Large** (≥ 90 cols): full ASCII NOUS wordmark (5 lines)
- **Medium** (60–89 cols): compact ASCII logo (4 lines)
- **Small** (< 60 cols): text label `NOUS`
- All logos are pure ASCII — safe on PowerShell, cmd.exe, and Linux

## Colour Palette

| Role          | Colour        |
|---------------|---------------|
| Labels        | bold white    |
| Values        | bright white  |
| Dividers      | plain text    |
| Success       | green         |
| Warning       | yellow        |
| Error         | red           |

No excessive colour.  No orange.  No emoji.  Professional terminal style.

## Prompt

```
nous >
```

Clean, minimal, professional.  Immediately communicates: "this is an
interactive Runtime shell, not a system shell."

## Shell Commands

| Command        | Description                              |
|----------------|------------------------------------------|
| `/help`        | Show all commands                        |
| `/status`      | Runtime health and stats                 |
| `/scan`        | Index project files                      |
| `/memory`      | Recent timeline events                   |
| `/tasks`       | Project tasks                            |
| `/providers`   | Registered providers                     |
| `/capabilities`| Available + unavailable capabilities     |
| `/packs`       | Installed packs                          |
| `/trace`       | Execution traces                         |
| `/settings`    | Project configuration                    |
| `/workspace`   | Workspace path and structure             |
| `/clear`       | Clear screen                             |
| `/exit`        | Exit shell                               |

## Session Model

Every shell session writes timeline events:

- `shell_started` — when the Runtime enters the shell
- `shell_exited` — when the user exits

On startup, the session summary shows:
- Last session's events
- Today's pending tasks
- Provider count

## Full-screen setup flows

Interactive setup and `nous provider add` use the terminal alternate screen when
standard input and output are attached to a compatible terminal:

- Up and Down move between choices.
- Enter accepts the highlighted choice.
- Escape returns to the previous step.
- Ctrl+C or Ctrl+D cancels without saving incomplete configuration.
- Secret input is masked and never echoed.

Set `NOUS_TUI=0` to use the line-oriented compatibility flow. Redirected input,
CI, and non-interactive sessions select compatibility mode automatically.

## History
- Up/Down arrows navigate command history (readline)
- Persisted to `.nous/history` across sessions
- Falls back to plain `input()` on Windows without readline

## Accessibility

Tested on:
- Windows PowerShell
- Windows Terminal
- cmd.exe
- Linux terminal (xterm, gnome-terminal, alacritty)
- Rich installed and absent

## Rich vs Plain Text

Rich provides colour markup resolution.  If rich is not installed, the
exact same layout renders in plain text — no missing features, no
import errors.

```bash
pip install nous-runtime[ui]   # enhanced colour rendering
```
