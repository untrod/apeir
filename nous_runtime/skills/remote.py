"""Exact Skill package bytes through the existing public-network gateway."""

from __future__ import annotations

from urllib.parse import urlsplit

from nous_runtime.evidence.web_gateway import WebGateway, WebRequest


def require_remote_url(source: str) -> None:
    """Require a credential-free, exact HTTPS locator before permission checks."""
    try:
        parts = urlsplit(source)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Skill source URL is invalid") from exc
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or any(ord(character) < 33 or ord(character) == 127 for character in source)
        or "\\" in source
        or port == 0
    ):
        raise ValueError(
            "Skill sources require credential-free HTTPS without query or fragment"
        )


class RemoteSkillGateway:
    """Skill acquisition policy over the single Runtime HTTP boundary."""

    def fetch_bytes(self, source: str, *, max_bytes: int) -> bytes:
        require_remote_url(source)
        acquired = WebGateway().fetch_bytes(
            WebRequest(
                url=source,
                timeout_seconds=30,
                max_size_bytes=max_bytes,
                max_redirects=0,
                max_retries=0,
                approval_requirement="required",
            )
        )
        if not acquired.response.ok:
            raise ValueError(
                acquired.response.error_message or "Skill source acquisition failed"
            )
        return acquired.body
