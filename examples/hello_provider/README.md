# Hello Provider

A credential-free Provider adapter using the public Provider contract.

```python
from examples.hello_provider.hello_provider import HelloProvider
from nous_runtime.provider.registry import ProviderRegistry

registry = ProviderRegistry()
provider_id = registry.install(HelloProvider())
try:
    result = registry.get(provider_id).invoke("example.greet", name="Nous")
    assert result["ok"]
finally:
    registry.remove(provider_id)
```

`remove()` unregisters only capabilities still owned by this Provider. Production credentials must be environment or credential-manager references; never add keys to an adapter manifest.