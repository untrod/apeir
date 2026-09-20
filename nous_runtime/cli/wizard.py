# -*- coding: utf-8 -*-
"""
First-run wizard for `nous init`.

Guides a new user through workspace creation, mode selection,
provider configuration, and initial pack installation.
"""

from __future__ import annotations

import os
import sys
from typing import Any


def run_wizard() -> dict[str, Any]:
    """Run the interactive first-run wizard. Returns user config dict."""
    config: dict[str, Any] = {
        "workspace": "",
        "mode": "personal",
        "providers": [],
        "packs": [],
    }

    print()
    print("Nous Runtime")
    from nous_runtime.version import __version__
    print(f"Version {__version__}")
    print()
    print("This wizard will help you set up your Nous environment.")
    print("Press Enter to accept defaults, or type your choice.")
    print()

    # Step 1: Workspace
    default_ws = os.path.join(os.path.expanduser("~"), "nous_workspace")
    ws = _prompt("Workspace directory", default_ws)
    config["workspace"] = ws
    os.makedirs(ws, exist_ok=True)
    print(f"  [OK] Workspace: {ws}")
    print()

    # Step 2: Mode
    print("Runtime mode:")
    print("  (1) Personal  - daily use, learning, automation")
    print("  (2) Developer - build packs and providers")
    print("  (3) Server    - headless deployment")
    print("  (4) Edge      - minimal, device-focused")
    mode_choice = _prompt("Select mode", "1")
    modes = {"1": "personal", "2": "developer", "3": "server", "4": "edge"}
    config["mode"] = modes.get(mode_choice, "personal")
    print(f"  [OK] Mode: {config['mode']}")
    print()

    # Step 3: Providers
    print("Configure AI providers:")
    print("  Providers are how the Runtime executes capabilities.")
    print("  You can add more later with: nous provider add")
    print()

    if _confirm("Configure an AI provider now?"):
        provider = _configure_provider()
        if provider:
            config["providers"].append(provider)

    # Step 4: Packs
    print()
    print("Install starter packs:")
    print("  (1) None - start empty")
    print("  (2) Developer Pack - code, git, project tools")
    print("  (3) All example packs")
    pack_choice = _prompt("Select", "1")
    if pack_choice == "2":
        config["packs"].append("packs/examples/hello_pack")
        print("  [OK] Will install Developer Pack")
    elif pack_choice == "3":
        config["packs"].append("packs/examples/hello_pack")
        config["packs"].append("packs/examples/study_pack")
        print("  [OK] Will install all example packs")

    # Summary
    print()
    print("Configuration summary")
    print("-" * 40)
    print(f"  Workspace:  {config['workspace']}")
    print(f"  Mode:       {config['mode']}")
    print(f"  Providers:  {len(config['providers'])} configured")
    print(f"  Packs:      {len(config['packs'])} selected")
    print()

    if not _confirm("Apply this configuration?"):
        print("Setup cancelled. Run `nous init` to try again.")
        sys.exit(0)

    # Apply
    _apply_config(config)
    return config


def _configure_provider() -> dict[str, Any] | None:
    """Interactive provider configuration."""
    print()
    print("  Available providers:")
    print("    (1) OpenAI   - GPT-4, GPT-3.5")
    print("    (2) DeepSeek - deepseek-chat")
    print("    (3) Claude   - claude-sonnet-4-6")
    print("    (4) Ollama   - local models")
    print("    (5) Custom   - any OpenAI-compatible API")
    choice = _prompt("  Select provider", "1")
    providers = {"1": "openai", "2": "deepseek", "3": "claude", "4": "ollama", "5": "custom"}
    name = providers.get(choice, "openai")

    api_key = _prompt(f"  API Key for {name}", "", secret=True)
    if not api_key:
        print("  [WARN] No key provided. Configure it later with NOUS_LLM_API_KEY.")
        return None

    endpoint = ""
    model = ""
    if name == "openai":
        endpoint = "https://api.openai.com/v1/chat/completions"
        model = "gpt-4"
    elif name == "deepseek":
        endpoint = "https://api.deepseek.com/v1/chat/completions"
        model = "deepseek-chat"
    elif name == "claude":
        endpoint = "https://api.anthropic.com/v1/messages"
        model = "claude-sonnet-4-6"
    elif name == "ollama":
        endpoint = "http://localhost:11434/v1/chat/completions"
        model = _prompt("  Model name", "llama3")
    else:
        endpoint = _prompt("  API Endpoint URL", "")
        model = _prompt("  Model name", "")

    print(f"  [OK] Provider: {name} ({model})")
    return {"name": name, "api_key": api_key, "endpoint": endpoint, "model": model}


def _apply_config(config: dict[str, Any]) -> None:
    """Apply the configuration to the system."""
    import json

    os.makedirs(config["workspace"], exist_ok=True)
    providers = []
    for provider in config.get("providers", []):
        api_key = str(provider.get("api_key") or "")
        if api_key:
            os.environ["NOUS_LLM_API_KEY"] = api_key
        providers.append(
            {
                key: value
                for key, value in provider.items()
                if key.lower() not in {"api_key", "token", "secret", "password"}
            }
            | {"api_key_env": "NOUS_LLM_API_KEY"}
        )

    persisted_config = dict(config)
    persisted_config["providers"] = providers
    config_path = os.path.join(config["workspace"], "config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(persisted_config, f, indent=2, default=str)
    try:
        os.chmod(config_path, 0o600)
    except OSError:
        pass

    env_file = os.path.join(config["workspace"], ".env.example")
    with open(env_file, "w", encoding="utf-8") as f:
        f.write("NOUS_LLM_API_KEY=\n")
        if providers:
            provider = providers[0]
            f.write(f"NOUS_LLM_API_URL={provider.get('endpoint', '')}\n")
            f.write(f"NOUS_LLM_MODEL={provider.get('model', '')}\n")

    print(f"  Configuration saved to {config_path}")
    print("  Provider credentials were not stored; set NOUS_LLM_API_KEY in the environment.")

    # Install packs
    for pack_path in config.get("packs", []):
        try:
            from nous_runtime.services.packs import install_pack
            full = os.path.join(os.getcwd(), pack_path)
            if os.path.isdir(full):
                install_pack(full)
                print(f"  Pack installed: {pack_path}")
        except Exception as e:
            print(f"  Pack install failed ({pack_path}): {e}")


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt the user with a default value."""
    if secret:
        import msvcrt
        suffix = " [hidden]: "
    elif default:
        suffix = f" [{default}]: "
    else:
        suffix = ": "
    sys.stdout.write(f"  {label}{suffix}")
    sys.stdout.flush()

    if secret:
        chars = []
        while True:
            ch = msvcrt.getch() if hasattr(msvcrt, 'getch') else sys.stdin.read(1)
            if ch in (b'\r', b'\n', '\r', '\n'):
                print()
                break
            elif ch in (b'\x08', b'\x7f', '\x08', '\x7f'):
                if chars:
                    chars.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            else:
                ch = ch.decode() if isinstance(ch, bytes) else ch
                chars.append(ch)
                sys.stdout.write('*')
                sys.stdout.flush()
        return ''.join(chars)
    else:
        val = input()
        return val if val else default


def _confirm(prompt: str) -> bool:
    """Ask a yes/no question."""
    ans = _prompt(f"{prompt} (y/n)", "y").lower()
    return ans in ("y", "yes")
