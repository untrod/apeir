# Nous Tool Template

Create a custom tool plugin in 30 minutes.

## Quick Start
```bash
nous dev create-tool my-tool
```

## Tool Implementation
```python
class MyTool:
    def __init__(self):
        self.name = "my_tool"
        self.description = "What this tool does"
        self.parameters = {
            "input_file": {"type": "string", "required": True},
            "options": {"type": "object", "required": False},
        }
        self.permissions = ["file.read"]

    def execute(self, params: dict, context: dict) -> dict:
        input_file = params["input_file"]
        result = self._process(input_file)
        return {"status": "success", "output": result}
```

## Validation
```bash
nous dev validate-tool --manifest tool.json
nous dev test-tool --input '{"input_file": "test.txt"}'
```
