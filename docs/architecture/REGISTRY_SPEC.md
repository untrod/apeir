# Pack Registry Specification v1.0

## Purpose

The Pack Registry is the discovery and distribution mechanism for Nous packs. It allows developers to publish packs and users to discover and install them.

## Registry Types

| Type | Scope | Examples |
|------|-------|----------|
| **Official** | Maintained by Nous project | Core packs, reference implementations |
| **Community** | Published by anyone | Domain packs, integrations, tools |
| **Enterprise** | Private registries | Internal company packs, proprietary providers |

## Pack Metadata

```yaml
name: my_pack
version: 1.0.0
description: What this pack does
author:
  name: Author Name
  email: author@example.com
license: Apache-2.0
keywords: [study, knowledge, review]
category: learning

capabilities:
  - my_pack.action

providers:
  - MyProvider

dependencies:
  runtime: ">=1.0"

permissions:
  - read:knowledge
  - write:knowledge

registry:
  namespace: community     # official | community | enterprise
  visibility: public       # public | private
  downloads: 0
  rating: 0.0
```

## Protocol (v1.1+)

```
GET  /registry/search?q=study&category=learning
GET  /registry/pack/{name}
GET  /registry/pack/{name}/versions
GET  /registry/pack/{name}/{version}/download
POST /registry/pack/publish
```

## Namespace Rules

- `official/*` — maintained by Nous project
- `community/*` — published by anyone, reviewed by community
- `enterprise/*` — private registries, org-specific

## For v1.1.0

- Registry protocol is defined but NOT implemented
- Packs installed from local directories
- Registry implementation planned for v1.2.0
