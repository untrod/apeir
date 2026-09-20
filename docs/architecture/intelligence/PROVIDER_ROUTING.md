# Intelligent Provider Router

## Purpose

Remove manual provider selection. The Runtime selects the best provider based on experience and preferences.

## Routing Factors

| Factor | Weight | Description |
|--------|--------|-------------|
| Health | 0.25 | Provider must be healthy (down providers excluded) |
| Success Rate | 0.35 | Historical success rate from Experience Engine |
| Latency | 0.15 | Average execution time |
| Privacy | 0.15 | Local vs cloud preference |
| Speed | 0.10 | User preference for fastest provider |

## Routing Preferences

```python
from nous_runtime.provider.router import route, RoutingPreference

# Default: balanced
provider = route("model.reason")

# Privacy-first: prefer local
provider = route("model.reason", RoutingPreference(privacy="high"))

# Speed-first: prefer fastest
provider = route("model.reason", RoutingPreference(speed="fastest"))
```

## Experience-Based Selection

The router uses execution history to rank providers. If Provider A has 95% success rate and Provider B has 70%, Provider A is selected.

Cold start: unknown providers get a neutral score and are tried eventually.
