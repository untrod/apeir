"""Release-gate audit for the unified Runtime model execution boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from nous_runtime.model_runtime.compatibility import compatibility_metrics
from nous_runtime.model_runtime.factory import gateway_service
from nous_runtime.runtime.bootstrap import NousRuntime


_DIRECT_PATTERNS = (
    (
        "direct_provider",
        re.compile(r"\bprovider\s*\.\s*invoke\s*\("),
    ),
    (
        "direct_openai_sdk",
        re.compile(
            r"\b(?:OpenAI|AsyncOpenAI)\s*\(|\bopenai\.(?!com\b)"
        ),
    ),
    (
        "direct_anthropic_sdk",
        re.compile(
            r"\b(?:Anthropic|AsyncAnthropic)\s*\(|"
            r"\banthropic\.(?!com\b)"
        ),
    ),
)
_REMOTE_MODEL_FILES = {
    "remote_terminal/brain_llm.py",
    "remote_terminal/doc_engine.py",
    "remote_terminal/embedding.py",
}
_GATEWAY_PATTERN = re.compile(
    r"\b(?:GatewayRequest|ModelRequest)\s*\(|"
    r"\b(?:facade|gateway)\.(?:invoke|invoke_sync|try_invoke_sync)\s*\("
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\b
    \s*=\s*
    (?P<quote>["'])(?P<value>[^"']+)(?P=quote)
    """
)


@dataclass(frozen=True)
class RuntimeAuditFinding:
    category: str
    path: str
    line: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "path": self.path,
            "line": self.line,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RuntimeAuditReport:
    root: str
    gateway_calls: int
    direct_provider_calls: int
    deprecated_calls: int
    security_findings: int
    gateway_configured: bool
    findings: tuple[RuntimeAuditFinding, ...]

    @property
    def gateway_percentage(self) -> float:
        total = self.gateway_calls + self.direct_provider_calls
        return 100.0 if total == 0 else round(
            self.gateway_calls / total * 100,
            2,
        )

    @property
    def passed(self) -> bool:
        return (
            self.gateway_configured
            and self.direct_provider_calls == 0
            and self.deprecated_calls == 0
            and self.security_findings == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.passed,
            "root": self.root,
            "gateway": {
                "configured": self.gateway_configured,
                "calls": self.gateway_calls,
                "percentage": self.gateway_percentage,
            },
            "direct_provider": self.direct_provider_calls,
            "deprecated": self.deprecated_calls,
            "security": (
                "PASS" if self.security_findings == 0 else "FAIL"
            ),
            "security_findings": self.security_findings,
            "findings": [item.to_dict() for item in self.findings],
        }


def audit_runtime(
    root: str | Path = ".",
    *,
    runtime: NousRuntime | None = None,
    source_roots: Iterable[str] = ("nous_runtime", "remote_terminal"),
) -> RuntimeAuditReport:
    """Audit source paths and current compatibility telemetry."""
    base = Path(root).resolve()
    active_runtime = runtime or NousRuntime.bootstrap(
        workspace_root=str(base)
    )
    gateway = gateway_service.get(required=False)
    findings: list[RuntimeAuditFinding] = []
    gateway_calls = 0

    for relative_root in source_roots:
        source_root = base / relative_root
        if not source_root.exists():
            continue
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(base).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            gateway_calls += len(_GATEWAY_PATTERN.findall(text))
            if _allowed_protocol_path(relative):
                continue
            for line_number, line in enumerate(
                text.splitlines(),
                start=1,
            ):
                for category, pattern in _DIRECT_PATTERNS:
                    if pattern.search(line):
                        findings.append(
                            RuntimeAuditFinding(
                                category,
                                relative,
                                line_number,
                                "business code bypasses ModelGatewayFacade",
                            )
                        )
                if _is_direct_model_http(relative, line):
                    findings.append(
                        RuntimeAuditFinding(
                            "direct_model_http",
                            relative,
                            line_number,
                            "model HTTP call is outside a registered adapter",
                        )
                    )
                if _contains_hardcoded_secret(line):
                    findings.append(
                        RuntimeAuditFinding(
                            "hardcoded_secret",
                            relative,
                            line_number,
                            "possible credential literal in source",
                        )
                    )

    direct = sum(
        item.category != "hardcoded_secret"
        for item in findings
    )
    security = sum(
        item.category == "hardcoded_secret"
        for item in findings
    )
    metrics = compatibility_metrics()
    deprecated = int(metrics.get("direct_fallbacks", 0))
    snapshot = active_runtime.snapshot()
    return RuntimeAuditReport(
        root=str(base),
        gateway_calls=gateway_calls,
        direct_provider_calls=direct,
        deprecated_calls=deprecated,
        security_findings=security,
        gateway_configured=bool(
            gateway is not None and snapshot.gateway_configured
        ),
        findings=tuple(findings),
    )


def _allowed_protocol_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith("nous_runtime/provider/adapters/")
        or normalized == "nous_runtime/model_runtime/adapters.py"
        or normalized.startswith("nous_runtime/model_distribution/")
        or normalized.startswith("nous_runtime/sdk/")
        or normalized.startswith("nous_runtime/api/")
        or normalized.startswith("nous_runtime/connectivity/")
        or normalized.startswith("nous_runtime/cli/provider_")
        or normalized == "nous_runtime/cli/doctor.py"
        or normalized == "nous_runtime/cli/wizard.py"
    )


def _is_direct_model_http(path: str, line: str) -> bool:
    if path not in _REMOTE_MODEL_FILES:
        return False
    compact = line.replace(" ", "")
    if path == "remote_terminal/brain_llm.py":
        return (
            "post_json(" in compact
            or "_no_proxy.open(" in compact
        )
    if path == "remote_terminal/embedding.py":
        return "urlopen(" in compact
    if path == "remote_terminal/doc_engine.py":
        return (
            "urllib.request.Request(" in compact
            or "no_proxy.open(" in compact
        )
    return False


def _contains_hardcoded_secret(line: str) -> bool:
    match = _SECRET_ASSIGNMENT_PATTERN.search(line)
    if match is None:
        return False
    value = match.group("value").strip()
    normalized = value.casefold()
    if len(value) < 12:
        return False
    return not any(
        marker in normalized
        for marker in (
            "change-me",
            "changeme",
            "configured",
            "example",
            "placeholder",
            "pre_shared_key",
            "redacted",
            "your-",
        )
    )


__all__ = [
    "RuntimeAuditFinding",
    "RuntimeAuditReport",
    "audit_runtime",
]
