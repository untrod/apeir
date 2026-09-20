"""OpenClaw ↔ Nous interoperability layer.

Maps OpenClaw gateway concepts to Nous kernel primitives:
  - Gateway Session → AgentProcess
  - Workspace → Namespace / Workspace
  - Skill → Capability / Tool Provider
  - Channel Message → Workload Input
  - Cron → Automation Workload
  - Node → Nous Node
  - Sandbox → Isolation Profile / Effect Gate
  - Agent State → Context Address Space
  - Tool Result → Context Page / Artifact

RC9 Gate F — interoperability verification.
"""
