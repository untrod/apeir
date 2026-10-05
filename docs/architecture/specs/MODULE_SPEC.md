# Module Specification v1.0

> Standard for writing Nous modules without modifying the kernel.

## Module Manifest

```json
{
  "module_id": "learning",
  "version": "1.0.0",
  "name": "Learning Engine",
  "description": "Example Study Pack with knowledge tracking and spaced repetition",
  "author": "Nous",
  "events": [
    "learning.question.asked",
    "learning.session.started",
    "learning.session.ended",
    "learning.review.due",
    "learning.mistake.recorded"
  ],
  "capabilities": [
    "learning.analyze",
    "learning.plan",
    "learning.review",
    "learning.report"
  ],
  "permissions": [
    "read_learning_state",
    "write_learning_state",
    "read_knowledge_base",
    "send_notification"
  ],
  "dependencies": {
    "nous_core": ">=0.1.0",
    "learn_db": ">=1.0.0"
  },
  "config": {
    "daily_review_hour": 21,
    "max_questions_per_session": 50
  }
}
```

## Module Lifecycle

```
loaded -> initialized -> running
                           ↓
                        paused -> resumed
                           ↓
                        stopped -> unloaded
```

## Permission Model

| Permission | Scope |
|-----------|-------|
| `read_*` | Read-only access to subsystem |
| `write_*` | Write access to subsystem |
| `send_notification` | Can create notifications |
| `invoke_capability` | Can call other capabilities |
| `manage_devices` | Can register/modify devices |
| `access_secrets` | Can read encrypted config (restricted) |

## Isolation Rules

1. Module failure must not crash the kernel
2. Module cannot access another module's internal state
3. Module cannot bypass the capability system
4. Module cannot disable security policies
5. Module permissions are checked on every capability invocation

## Directory Layout

```
modules/
├── learning/
│   ├── module.json        # manifest
│   ├── __init__.py        # entry point
│   ├── capabilities.py    # capability handlers
│   └── events.py          # event handlers
├── notification/
├── model_router/
└── device/
```
