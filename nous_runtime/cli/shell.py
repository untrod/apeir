# -*- coding: utf-8 -*-
"""
Interactive Terminal -the `nous` shell.

Supports natural language input and slash commands.
All commands route through the unified Runtime API.

Usage:
    nous              # Enter interactive mode
    nous run ...      # Execute capability
"""

from __future__ import annotations

import os
from typing import Any

# Shell State

class ShellState:
    """Mutable state for the interactive shell session."""
    def __init__(self):
        self.running = True
        self.workspace = os.getcwd()
        self.last_command: str = ""
        self.history: list[str] = []


_state = ShellState()


# Command Registry

COMMANDS: dict[str, Any] = {}


def cmd(name: str, help_text: str):
    """Decorator to register a slash command."""
    def decorator(fn):
        COMMANDS[name] = {"fn": fn, "help": help_text}
        return fn
    return decorator


# Slash Commands

@cmd("help", "Show this help message")
def _cmd_help(args: list[str]) -> str:
    lines = ["Available commands:", ""]
    for name, info in sorted(COMMANDS.items()):
        lines.append(f"  /{name:<16} {info['help']}")
    lines.append("")
    lines.append("Or type anything to plan and execute with the Runtime.")
    return "\n".join(lines)


@cmd("status", "Show Runtime status")
def _cmd_status(args: list[str]) -> str:
    try:
        from nous_runtime.runtime.lifecycle import Runtime
        from nous_runtime.services.packs import count_packs
        rt = Runtime()
        s = rt.status()
        return (
            f"Runtime v{s.version}  {'running' if s.running else 'not running'}\n"
            f"  Providers:    {s.providers}\n"
            f"  Capabilities: {s.capabilities}\n"
            f"  Packs:        {count_packs()}\n"
            f"  Devices:      {s.devices}\n"
            f"  Events:       {s.events_total}\n"
            f"  Jobs pending: {s.jobs_pending}\n"
            f"  Demo mode:    {'on' if s.demo_mode else 'off'}"
        )
    except Exception as e:
        return f"Runtime status unavailable: {e}"


@cmd("providers", "List registered providers")
def _cmd_providers(args: list[str]) -> str:
    try:
        from nous_runtime.services.providers import list_provider_summaries
        providers = list_provider_summaries()
        if not providers:
            return "No providers registered."
        lines = [f"{'Name':<24} {'Status':<12} {'Capabilities'}", "-" * 64]
        for p in providers:
            caps = ", ".join(p.get("capabilities", [])[:3])
            if len(p.get("capabilities", [])) > 3:
                caps += f" +{len(p['capabilities']) - 3}"
            status = p.get("health", {}).get("status", "?")
            lines.append(f"{p['name']:<24} {status:<12} {caps}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("capabilities", "List registered capabilities")
def _cmd_capabilities(args: list[str]) -> str:
    try:
        from nous_runtime.services.capabilities import list_capabilities
        caps = list_capabilities()
        if not caps:
            return "No capabilities registered."
        lines = [f"{'Name':<36} {'Provider':<16} {'Risk':<8}", "-" * 62]
        for c in caps[:30]:
            name = c.get("name", "?") if isinstance(c, dict) else str(c)
            provider = c.get("provider", "") if isinstance(c, dict) else ""
            risk = c.get("risk", "") if isinstance(c, dict) else ""
            lines.append(f"{name:<36} {provider:<16} {risk:<8}")
        if len(caps) > 30:
            lines.append(f"  ... +{len(caps) - 30} more")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("packs", "List installed packs")
def _cmd_packs(args: list[str]) -> str:
    try:
        from nous_runtime.services.packs import list_packs
        packs = list_packs()
        if not packs:
            return "No packs installed. Try: nous pack install packs/examples/hello_pack"
        lines = [f"{'Name':<24} {'Version':<10} {'Enabled':<8}", "-" * 44]
        for p in packs:
            lines.append(f"{p['name']:<24} {p['version']:<10} {str(p['enabled']):<8}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("jobs", "Show recent jobs")
def _cmd_jobs(args: list[str]) -> str:
    try:
        from nous_runtime.services.jobs import list_jobs
        all_jobs = list_jobs()
        if not all_jobs:
            return "No jobs recorded."
        jobs = all_jobs[-10:]
        lines = [f"{'ID':<30} {'Status':<12} {'Type'}", "-" * 56]
        for j in jobs:
            jid = (j.get("job_id") or j.get("id") or "?")[:28] if isinstance(j, dict) else str(j)[:28]
            status = j.get("status", "?") if isinstance(j, dict) else "?"
            jtype = j.get("type", "") if isinstance(j, dict) else ""
            lines.append(f"{jid:<30} {status:<12} {jtype}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("trace", "Show recent execution traces")
def _cmd_trace(args: list[str]) -> str:
    try:
        limit = int(args[0]) if args else 10
    except ValueError:
        limit = 10
    try:
        from nous_runtime.services.traces import get_recent_traces
        traces = get_recent_traces(limit)
        if not traces:
            return "No traces recorded."
        lines = [f"{'Trace ID':<30} {'Capability':<24} {'Decision'}", "-" * 66]
        for t in traces[:limit]:
            if isinstance(t, dict):
                tid = t.get("trace_id", "?")[:28]
                cap = t.get("capability", "?")[:22]
                dec = t.get("decision", "?")[:14]
                lines.append(f"{tid:<30} {cap:<24} {dec}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@cmd("clear", "Clear the screen")
def _cmd_clear(args: list[str]) -> str:
    os.system("cls" if os.name == "nt" else "clear")
    return ""


@cmd("quit", "Exit the shell")
def _cmd_quit(args: list[str]) -> str:
    _state.running = False
    return "Goodbye."


@cmd("exit", "Exit the shell")
def _cmd_exit(args: list[str]) -> str:
    return _cmd_quit(args)


# Shell Loop

def run_shell() -> None:
    """Run the interactive Nous shell."""
    print("Nous Runtime v1.0.0 -Interactive Shell")
    print("Type /help for commands, or anything to plan and execute.")
    print()

    while _state.running:
        try:
            user_input = input("nous> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        _state.history.append(user_input)
        _state.last_command = user_input

        # Slash commands
        if user_input.startswith("/"):
            parts = user_input[1:].split()
            cmd_name = parts[0].lower()
            cmd_args = parts[1:]

            handler = COMMANDS.get(cmd_name)
            if handler:
                result = handler["fn"](cmd_args)
                if result:
                    print(result)
            else:
                print(f"Unknown command: /{cmd_name}. Type /help for available commands.")
        else:
            # Natural language -route to Runtime
            print(f"[Planning] {user_input[:60]}...")
            try:
                from nous_runtime.capability.resolver import execute_capability
                result = execute_capability("model.reason", prompt=user_input)
                if result.ok:
                    content = result.result.get("content", "") if isinstance(result.result, dict) else str(result.result)
                    print(content[:500])
                else:
                    print(f"Error: {result.error_code} -{result.error}")
            except Exception as e:
                print(f"Runtime error: {e}")

        print()

    print("Shell closed.")


# Entry Point

def main():
    """Entry point for `nous` (no arguments = interactive shell)."""
    run_shell()


if __name__ == "__main__":
    main()
