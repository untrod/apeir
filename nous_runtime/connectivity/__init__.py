# -*- coding: utf-8 -*-
"""
Nous Connectivity — secure, durable node connectivity for the Nous Runtime.

Package structure:
  protocol/       — versioned immutable protocol contracts
  control_plane/  — server-side Gateway, NodeRegistry, TaskCoordinator
  node/           — outbound Node daemon
  delivery/       — reliable task delivery state machine
  capabilities/   — node capability runtime (system.echo, etc.)
  cli/            — CLI commands for server, node, task management
"""

from __future__ import annotations
