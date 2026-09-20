# Nous Runtime — Pack Model v1.0

> The Pack is the unit of domain knowledge in Nous Runtime.

---

## 1. What is a Pack?

A **Pack** is a self-contained, installable module that provides domain-specific knowledge and capabilities to the Runtime.

The Runtime itself contains **no domain knowledge**. It does not know about mathematics, medicine, industrial control, language learning, or any other domain. It only knows how to schedule capabilities, manage providers, enforce security, and execute workflows.

A Pack provides everything needed for a specific domain:

- Knowledge datasets
- Question banks
- Review schedules
- Subject taxonomies
- Domain-specific prompts
- Assessment logic

---

## 2. Why Packs Exist

### The Problem

Without Packs, domain knowledge leaks into the Runtime:

```python
# BAD: Runtime knows about specific exams
subjects = ["高数", "英语", "语文", "计算机"]
domains = ["考研", "专升本", "四六级"]
```

This makes the Runtime:
- Tied to one user's needs
- Impossible to reuse across domains
- Hard to maintain as knowledge changes

### The Solution

With Packs, the Runtime stays neutral:

```python
# GOOD: Runtime delegates to Pack
pack = workspace.load_pack("study_pack_v1")
subjects = pack.list_subjects()
domains = pack.list_stages()
```

---

## 3. Pack Types

### Study Pack
General-purpose learning and study management.
- Knowledge tree navigation
- Study session tracking
- Progress analytics
- Spaced repetition scheduling

### Knowledge Pack
A curated set of knowledge entries for a specific domain.
- Subject taxonomy
- Knowledge entries (title, content, prerequisites)
- Cross-references between entries
- Mastery tracking per entry

### Question Pack
A bank of exercises and assessments.
- Questions with answers and solution steps
- Difficulty ratings
- Bloom's taxonomy levels
- Error type classification

### Language Pack
Language-specific learning content.
- Vocabulary lists with definitions
- Grammar rules
- Reading comprehension passages
- Writing prompts

### Course Pack
Structured curriculum for a specific program.
- Course outline with chapters
- Lecture notes and slides
- Assignment specifications
- Exam blueprints

### Skill Pack
Task-oriented capability bundles.
- Step-by-step workflows
- Trigger conditions
- Required permissions
- Success criteria

### Device Pack
Hardware-specific integration.
- Device capability declarations
- Communication protocols
- Safety constraints
- Firmware specifications

### Industrial Pack
Domain packs for specific industries.
- Medical Pack
- PLC Pack (industrial control)
- Embedded Pack (microcontrollers)
- Finance Pack (trading, risk)
- Legal Pack (contracts, compliance)

---

## 4. Pack Lifecycle

```
Install -> Enable -> Configure -> Active
                                ↓
                           Disable -> Uninstall
```

### Install
A Pack is installed into the user's workspace. It registers its:
- Capabilities with the Capability Registry
- Events with the Event System
- Providers with the Provider Runtime

### Enable / Disable
Packs can be enabled or disabled without uninstalling. A disabled Pack:
- Does not receive events
- Its capabilities are not available for routing
- Its data remains intact

### Configure
Each Pack exposes configuration options:
- Subject preferences
- Schedule settings
- Difficulty thresholds
- Review intervals

---

## 5. Pack and Capability

A Pack **provides** capabilities. The Runtime **routes** to them.

```
User says: "Show me today's study plan"
     ↓
Router: matches capability "study.plan.today"
     ↓
Capability Registry: finds provider "study_pack_v1"
     ↓
Study Pack: generates plan from Knowledge Pack
     ↓
Returns: formatted plan with progress data
```

The Runtime never knows what "study" means. It only knows that `study.plan.today` is a registered capability provided by an active Pack.

---

## 6. Pack and Provider

A Pack may include one or more **Providers**:

| Pack | Providers |
|------|-----------|
| Study Pack | `study.plan`, `study.review`, `study.session` |
| Knowledge Pack | `knowledge.search`, `knowledge.tree`, `knowledge.mastery` |
| Question Pack | `question.generate`, `question.grade`, `question.analyze` |
| Language Pack | `language.vocab`, `language.grammar`, `language.reading` |

Each Provider implements the standard Provider interface (`register`, `capabilities`, `execute`, `health`).

---

## 7. Runtime Neutrality Principle

> **The Runtime does not contain domain knowledge.**
> **Domain knowledge is provided by installable Packs.**

This principle is enforced at the architecture level:

1. The Kernel has no `subject` or `exam` tables — those belong to Packs.
2. The Capability Registry has no domain-specific capabilities hardcoded.
3. System prompts contain no domain-specific instruction.
4. All knowledge data is owned by Packs, not the Runtime.

### What the Runtime Knows

- How to schedule tasks
- How to route capabilities
- How to enforce security
- How to manage state
- How to execute workflows

### What the Runtime Never Knows

- What subjects exist
- What exams the user is preparing for
- What industry the user works in
- What language the user is learning
- What knowledge the user has mastered

---

## 8. Creating a Pack

A Pack is defined by a manifest:

```json
{
  "pack_id": "study_pack_v1",
  "name": "Study Pack",
  "version": "1.0.0",
  "description": "General-purpose learning and study management",
  "author": "community",
  "capabilities": [
    "study.plan.create",
    "study.plan.today",
    "study.review.due",
    "study.session.start",
    "study.session.end",
    "study.progress.report"
  ],
  "providers": [
    "study_plan_provider",
    "study_review_provider",
    "study_session_provider"
  ],
  "dependencies": {
    "nous_core": ">=1.0.0"
  },
  "config": {
    "daily_review_hour": 21,
    "max_sessions_per_day": 8,
    "default_subjects": []
  }
}
```

---

## 9. Default Packs

Nous Runtime ships with no pre-installed Packs. The user installs Packs that match their needs.

Example Packs available from the community:
- `study_pack` — General learning management
- `language_pack` — Language learning (vocabulary, grammar, reading)
- `math_pack` — Mathematics (calculus, linear algebra, statistics)
- `code_pack` — Programming practice and code review

---

## 10. Relationship to Other Concepts

| Concept | Pack's Role |
|---------|------------|
| **Capability** | Pack declares what it can do |
| **Provider** | Pack implements how to do it |
| **Module** | Pack is a type of Module with domain data |
| **Workspace** | Pack is installed into a Workspace |
| **Protocol** | Pack communicates via standard protocols |
