# Nous Routing Policy Template

Create a custom model/plan routing policy.

## Policy Implementation
```python
class MyRoutingPolicy:
    name = "my_policy"
    version = "1.0.0"
    description = "Custom routing logic"

    def select_model(self, task, available_models):
        # Your logic here
        return available_models[0]

    def should_verify(self, task):
        return task.get("risk_class") in ("high", "critical")
```

## Registration
```bash
nous dev create-policy my-policy
nous policy register --policy my_policy --version 1.0.0
nous policy test --task-type code_audit --dry-run
```
