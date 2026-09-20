# Runtime Boundary v1.0

## What the Runtime IS

The Nous Runtime is the execution environment for intelligent capabilities. It manages the lifecycle of capabilities, providers, jobs, state, security, and protocols.

## What the Runtime IS NOT

- NOT a chatbot
- NOT an AI assistant
- NOT a learning platform
- NOT an exam preparation tool
- NOT an industrial controller
- NOT a medical system
- NOT a financial platform
- NOT a single model's API wrapper

## Boundary Rules

### Inside the Runtime (Kernel)
- Capability registration and execution
- Provider lifecycle management
- Job scheduling and dispatch
- Event sourcing
- Security policy enforcement
- Protocol handling
- State management
- Audit logging

### Outside the Runtime (Packs / Workspace)
- Subject taxonomies
- Exam definitions
- Knowledge content
- User goals and preferences
- Industry-specific workflows
- Domain-specific prompts
- Personal data

### Bridge (Runtime API)
- Knowledge state interface (read-only analytics)
- Study session lifecycle (generic)
- Progress tracking (generic metrics)
- Memory interface (key-value, embeddings)
- Workspace management

## Enforcement
- Kernel code must never import domain-specific constants
- System prompts must contain no domain instruction
- Database schemas must not include domain-specific columns
- Configuration must not hardcode domain defaults

## Violations Found (to fix)
1. `learn_db.py`: exam/course/phase tables -> move to Pack
2. `subject_experts.py`: hardcoded subjects -> move to Pack
3. `plan_engine.py`: exam-aware planning -> move to Pack
4. `brain_prompt.py`: study tutor persona -> generalize
