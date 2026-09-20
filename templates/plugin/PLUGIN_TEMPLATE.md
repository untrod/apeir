# Nous Plugin Template

Use this template to create a Nous plugin in under 30 minutes.

## Quick Start

```bash
nous dev create-plugin my-plugin
cd my-plugin
nous dev validate-plugin
nous dev test-plugin
nous dev package-plugin
```

## Plugin Structure

```
my-plugin/
├── plugin.json           # Plugin manifest
├── capabilities.json     # Declared capabilities
├── README.md
├── requirements.txt      # Python dependencies
└── src/
    ├── __init__.py
    └── main.py           # Plugin entrypoint
```

## plugin.json

```json
{
  "plugin_id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "entrypoint": "src.main:register",
  "capabilities": ["custom.tool.my_tool"],
  "permissions": ["file.read", "network.outbound"],
  "supported_platforms": ["windows", "linux", "macos"],
  "resource_requirements": {"memory_mb": 128},
  "protocol_compatibility": ["1.0"],
  "security_level": "medium",
  "publisher": "your-name",
  "description": "What this plugin does"
}
```

## capabilities.json

```json
{
  "capabilities": [
    {
      "capability_id": "custom.tool.my_tool",
      "name": "My Custom Tool",
      "description": "Does something useful",
      "category": "tool",
      "risk_level": "low",
      "side_effect_class": "read_only",
      "reversibility": "reversible",
      "required_permissions": ["file.read"],
      "executor_type": "provider"
    }
  ]
}
```

## Entrypoint (src/main.py)

```python
def register(registry):
    """Called when plugin is loaded."""
    from .my_tool import MyTool
    registry.register_tool("custom.tool.my_tool", MyTool())
```

## Validation

```bash
nous dev validate-plugin    # Check manifest, permissions, signatures
nous dev inspect-permissions # See what permissions are declared vs used
nous dev test-plugin        # Run plugin in sandbox
nous dev package-plugin     # Create distributable package
nous dev publish-check      # Check readiness for registry submission
```
