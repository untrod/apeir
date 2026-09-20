# -*- coding: utf-8 -*-
"""Prompt Injection Guard — external content is UNTRUSTED by default.

Implements: instruction/data separation, external instruction detection,
tool invocation gate, URL validation, SSRF protection, download scanning,
sandbox, approval escalation, output sanitization.

Web content must NEVER gain system-level instruction authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class InjectionCheckResult:
    """Result of injection scanning."""
    safe: bool = True
    risk_level: str = "low"   # low, medium, high, critical
    detected_patterns: list[str] = field(default_factory=list)
    blocked: bool = False
    reason: str = ""
    sanitized_content: str = ""


class InjectionGuard:
    """Scans external content for prompt injection attempts."""

    # Known injection patterns
    INJECTION_PATTERNS = [
        (r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|directions?|prompts?)", "high", "instruction_override"),
        (r"(?i)(you\s+are|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+(now|from\s+now\s+on)", "high", "role_redefinition"),
        (r"(?i)(output|print|display|show)\s+(your\s+)?(system\s+)?(prompt|instructions?|rules?)", "high", "prompt_extraction"),
        (r"(?i)(delete|remove|forget)\s+(all\s+)?(previous\s+)?(conversation|messages?|context)", "medium", "context_deletion"),
        (r"(?i)execute\s+(this\s+)?(command|code|script)\s*[:;]", "critical", "command_injection"),
        (r"(?i)(download|fetch|curl|wget)\s+(http|https)://", "medium", "ssrf_attempt"),
        (r"(?i)(sudo|admin|root)\s+(access|privilege)", "high", "privilege_escalation"),
        (r"(?i)(bypass|override|disable)\s+(security|safety|guard|filter)", "critical", "security_bypass"),
    ]

    def scan(self, content: str, source: str = "unknown") -> InjectionCheckResult:
        """Scan content for injection patterns."""
        result = InjectionCheckResult()

        for pattern, severity, pattern_name in self.INJECTION_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                result.detected_patterns.append(pattern_name)
                if severity == "critical":
                    result.risk_level = "critical"
                    result.blocked = True
                elif severity == "high" and result.risk_level != "critical":
                    result.risk_level = "high"
                elif severity == "medium" and result.risk_level not in ("critical", "high"):
                    result.risk_level = "medium"

        if result.detected_patterns:
            result.safe = False
            prefix = "Blocked" if result.blocked else "Detected"
            result.reason = f"{prefix}: {', '.join(result.detected_patterns)}"

        # Always sanitize external content
        result.sanitized_content = self._sanitize(content)

        return result

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Validate a URL for SSRF protection."""
        # Block private/internal IPs
        blocked_prefixes = [
            "http://127.", "http://10.", "http://172.16.", "http://172.17.",
            "http://172.18.", "http://172.19.", "http://172.20.", "http://172.21.",
            "http://172.22.", "http://172.23.", "http://172.24.", "http://172.25.",
            "http://172.26.", "http://172.27.", "http://172.28.", "http://172.29.",
            "http://172.30.", "http://172.31.", "http://192.168.", "http://169.254.",
            "http://[::1]", "http://localhost", "http://0.0.0.0",
            "file://", "ftp://", "gopher://",
        ]
        url_lower = url.lower()
        for prefix in blocked_prefixes:
            if url_lower.startswith(prefix):
                return False, f"Blocked URL pattern: {prefix}..."

        if not url_lower.startswith(("https://", "http://")):
            return False, "Only HTTP/HTTPS URLs allowed"

        return True, "URL valid"

    def _sanitize(self, content: str) -> str:
        """Sanitize content to reduce injection risk."""
        # Remove null bytes
        content = content.replace("\x00", "")
        # Truncate extremely long content
        if len(content) > 100_000:
            content = content[:100_000] + "\n[CONTENT TRUNCATED]"
        return content
