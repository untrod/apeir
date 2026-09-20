# -*- coding: utf-8 -*-
"""Developer CLI commands -nous dev new pack/validate/test."""

from __future__ import annotations

import os
from pathlib import Path

import typer

dev_app = typer.Typer(help="Developer tools")
new_app = typer.Typer(help="Scaffold new components")
dev_app.add_typer(new_app, name="new")


# Templates

PACK_TEMPLATE = {
    "pack.yaml": """name: {name}
version: 0.1.0
description: {description}

capabilities:
  - {name}.hello

providers:
  - HelloProvider

dependencies:
  runtime: ">=1.0"

config:
  greeting: "Hello from {name}!"
""",
    "src": {
        "__init__.py": '''# -*- coding: utf-8 -*-
"""{name} -{description}"""

from __future__ import annotations


def register(pack):
    """Called when the pack is installed."""
    from nous_runtime.services.providers import register_adapter
    from .providers import HelloProvider
    register_adapter(HelloProvider())
    pack.registered_providers.append("HelloProvider")
''',
        "providers.py": '''# -*- coding: utf-8 -*-
"""{name} providers."""

from __future__ import annotations

from nous_runtime.services.providers import Provider


class HelloProvider(Provider):
    """Example provider for {name}."""

    name = "{name}_hello"
    version = "0.1.0"

    def list_capabilities(self) -> list[str]:
        return ["{name}.hello"]

    def invoke(self, capability_id: str, **params) -> dict:
        greeting = params.get("greeting", "Hello from {name}!")
        return {{"ok": True, "message": greeting}}

    def health(self) -> dict:
        return {{"status": "ok"}}
''',
    },
    "tests": {
        "__init__.py": "# {name} tests\n",
        "test_providers.py": '''# -*- coding: utf-8 -*-
"""Tests for {name} providers."""


def test_hello_provider():
    from .src.providers import HelloProvider

    p = HelloProvider()
    caps = p.list_capabilities()
    assert "{name}.hello" in caps

    result = p.invoke("{name}.hello")
    assert result["ok"] is True
    assert "message" in result

    health = p.health()
    assert health["status"] == "ok"
''',
    },
    "README.md": """# {name}

{description}

## Install

```bash
nous pack install .
```

## Test

```bash
nous dev test
```

## Capabilities

- `{name}.hello` -Returns a greeting message.
""",
}


# nous dev new pack

@new_app.command("pack")
def new_pack(
    name: str = typer.Argument(..., help="Pack name (snake_case)"),
    description: str = typer.Option("A Nous Runtime pack", help="Pack description"),
    output: str = typer.Option(".", help="Output directory"),
):
    """Scaffold a new pack from template."""
    pack_dir = os.path.join(output, name)
    if os.path.exists(pack_dir):
        typer.echo(f"Error: '{pack_dir}' already exists.")
        raise typer.Exit(code=1)

    os.makedirs(pack_dir, exist_ok=True)

    # Write pack.yaml
    yaml_content = PACK_TEMPLATE["pack.yaml"].format(name=name, description=description)
    with open(os.path.join(pack_dir, "pack.yaml"), "w", encoding="utf-8") as f:
        f.write(yaml_content)

    # Write src/
    src_dir = os.path.join(pack_dir, "src")
    os.makedirs(src_dir, exist_ok=True)
    for filename, content in PACK_TEMPLATE["src"].items():
        formatted = content.format(name=name, description=description)
        with open(os.path.join(src_dir, filename), "w", encoding="utf-8") as f:
            f.write(formatted)

    # Write tests/
    tests_dir = os.path.join(pack_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    for filename, content in PACK_TEMPLATE["tests"].items():
        with open(os.path.join(tests_dir, filename), "w", encoding="utf-8") as f:
            f.write(content.format(name=name))

    # Write README
    with open(os.path.join(pack_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(PACK_TEMPLATE["README.md"].format(name=name, description=description))

    typer.echo(f"Pack '{name}' created at {pack_dir}")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo(f"  cd {name}")
    typer.echo("  nous dev validate")
    typer.echo("  nous dev test")
    typer.echo("  nous pack install .")
    typer.echo(f"  nous capability run {name}.hello")


@new_app.command("template")
def new_template(
    kind: str = typer.Argument(..., help="Template kind"),
    name: str = typer.Argument(..., help="Component name (snake_case)"),
    output: Path = typer.Option(Path("."), help="Parent output directory"),
):
    """Create a reviewable Runtime ecosystem template."""
    from nous_runtime.sdk.developer import render_template

    destination = (output.resolve() / name)
    files = render_template(kind, name)
    conflicts = [destination / relative for relative in files if (destination / relative).exists()]
    if conflicts:
        typer.echo(f"Error: '{conflicts[0]}' already exists.")
        raise typer.Exit(code=1)
    destination.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    typer.echo(f"{kind.title()} template '{name}' created at {destination}")

# nous dev validate

@dev_app.command("validate")
def dev_validate(
    path: str = typer.Option(".", help="Path to pack directory"),
):
    """Validate a pack's pack.yaml."""
    from nous_runtime.pack.manifest import PackManifest

    try:
        manifest = PackManifest.from_file(path)
        typer.echo(f"OK: {manifest.name} v{manifest.version} -valid")
        typer.echo(f"   Description: {manifest.description}")
        typer.echo(f"   Capabilities: {', '.join(manifest.capabilities) or '(none)'}")
        typer.echo(f"   Providers: {', '.join(manifest.providers) or '(none)'}")
        if manifest.dependencies:
            typer.echo(f"   Dependencies: {manifest.dependencies}")
    except Exception as e:
        typer.echo(f"ERROR: Validation failed: {e}")
        raise typer.Exit(code=1)


# nous dev test

@dev_app.command("test")
def dev_test(
    path: str = typer.Option(".", help="Path to pack directory"),
):
    """Run a pack's tests."""
    import subprocess
    import sys

    tests_dir = os.path.join(path, "tests")
    if not os.path.isdir(tests_dir):
        typer.echo("No tests/ directory found.")
        return

    typer.echo(f"Running tests in {tests_dir}...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", tests_dir, "-q"],
        cwd=path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr or ""
        if "No module named pytest" in stderr or "No module named pytest" in (result.stdout or ""):
            typer.echo("pytest is not installed.")
            typer.echo("Install developer dependencies:")
            typer.echo('  pip install "nous-runtime[dev]"')
        else:
            typer.echo(result.stdout or stderr)
        raise typer.Exit(code=result.returncode)
    else:
        typer.echo(result.stdout or "Tests passed.")


# nous dev new provider

PROVIDER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""{class_name} -{description}"""

from __future__ import annotations

from nous_runtime.services.providers import Provider


class {class_name}(Provider):
    """Provider for {description}."""

    name = "{provider_name}"
    version = "0.1.0"
    provider_id = "{provider_id}"

    def list_capabilities(self) -> list[str]:
        return ["{capability}"]

    def invoke(self, capability_id: str, **params) -> dict:
        if capability_id == "{capability}":
            # TODO: implement your logic here
            return {{"ok": True, "message": "Hello from {provider_name}!"}}
        return {{"ok": False, "error": f"Unknown capability: {{capability_id}}"}}

    def health(self) -> dict:
        return {{"status": "ok"}}
'''


@new_app.command("provider")
def new_provider(
    name: str = typer.Argument(..., help="Provider name (snake_case)"),
    capability: str = typer.Option("", help="Capability ID (e.g. my_provider.action)"),
    description: str = typer.Option("A Nous Runtime provider", help="Provider description"),
    output: str = typer.Option(".", help="Output directory"),
):
    """Scaffold a new provider from template."""
    # Generate names
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Provider"
    provider_id = name + "_v1"
    cap = capability or f"{name}.action"

    content = PROVIDER_TEMPLATE.format(
        class_name=class_name,
        provider_name=name,
        provider_id=provider_id,
        capability=cap,
        description=description,
    )

    out_path = os.path.join(output, f"{name}.py")
    if os.path.exists(out_path):
        typer.echo(f"Error: '{out_path}' already exists.")
        raise typer.Exit(code=1)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    typer.echo(f"Provider '{name}' created at {out_path}")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo(f"  1. Edit {out_path} -implement invoke()")
    typer.echo("  2. Register in your pack's src/__init__.py:")
    typer.echo(f"     from .{name} import {class_name}")
    typer.echo(f"     register_adapter({class_name}())")
    typer.echo("  3. nous dev validate")
    typer.echo("  4. nous pack install .")
