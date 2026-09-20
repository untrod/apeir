"""Legacy compatibility boundary for ``remote_terminal.nous_core``.

Runtime modules must depend on this package instead of importing legacy
``remote_terminal.nous_core`` modules directly. This keeps the remaining
legacy surface explicit while Nous Runtime 2.0 migrates ownership into
runtime-native services.
"""

__all__ = [
    "automation",
    "capability",
    "db",
    "demo_mode",
    "devices",
    "events",
    "ids",
    "jobs",
    "notifications",
    "protocol",
    "provider",
    "reasoning",
    "security",
    "study_session",
    "time",
]

