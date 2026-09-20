"""Resolve Provider credentials from references without persisting secret values."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class CredentialStatus:
    reference: str
    source: str
    available: bool
    detail: str


class CredentialStoreUnavailable(RuntimeError):
    """Raised when an optional operating-system credential backend is absent."""


def resolve_credential(reference: str) -> str:
    """Resolve an environment or OS secret-store reference."""
    if not reference:
        return ""
    source, service, account = _parse_reference(reference)
    if source == "env":
        return os.environ.get(service, "")
    keyring = _keyring()
    return str(keyring.get_password(service, account) or "")


def store_credential(reference: str, value: str) -> None:
    """Store a credential through the optional OS-backed keyring."""
    source, service, account = _parse_reference(reference)
    if source == "env":
        raise ValueError("Environment references are set outside Nous")
    if not value:
        raise ValueError("Credential value is empty")
    _keyring().set_password(service, account, value)


def validate_environment_variable_name(name: str) -> str:
    """Return a normalized environment-variable name or raise safely.

    Error text intentionally never includes the rejected value because users can
    accidentally paste credential material into a variable-name prompt.
    """
    normalized = str(name).strip()
    if not _ENVIRONMENT_NAME.fullmatch(normalized):
        raise ValueError(
            "Invalid environment-variable name. Enter a name such as "
            "DEEPSEEK_API_KEY, not the API key itself."
        )
    return normalized


def credential_status(reference: str, *, authentication_required: bool | None = None) -> CredentialStatus:
    """Describe availability without exposing the credential value.

    When *authentication_required* is ``False`` the provider explicitly
    declares that no credential is needed (e.g. Ollama).  When it is
    ``None`` (the default) the caller has not made a declaration and the
    empty-reference case returns *Not configured* rather than
    *Not required*.
    """
    if not reference:
        if authentication_required is False:
            return CredentialStatus("", "none", True, "Not required")
        return CredentialStatus("", "none", False, "Not configured")
    try:
        source, service, _ = _parse_reference(reference)
        value = resolve_credential(reference)
    except (CredentialStoreUnavailable, ValueError) as exc:
        return CredentialStatus(reference, "secret-store", False, str(exc))
    label = "Environment variable" if source == "env" else "Secret store"
    detail = "Available" if value else "Missing"
    return CredentialStatus(reference, label, bool(value), detail)


def describe_credential_reference(reference: str) -> str:
    """Return a safe display label containing no credential material."""
    if not reference:
        return "Not required"
    source, service, account = _parse_reference(reference)
    if source == "env":
        return f"Environment variable - {service}"
    return f"OS secret store - {service}/{account}"


def credential_fix_suggestion(status: CredentialStatus) -> str:
    """Return an actionable fix for an unavailable credential; '' when fine."""
    if status.available:
        return ""
    if not status.reference:
        return "Configure a credential with 'nous provider add'"
    try:
        source, service, account = _parse_reference(status.reference)
    except ValueError:
        return (
            "The credential reference could not be parsed."
            " Re-create the provider with 'nous provider add',"
            " then run 'nous provider doctor'."
        )
    if source == "env":
        example = (
            f"$env:{service}='<your-key>'"
            if os.name == "nt"
            else f"export {service}=<your-key>"
        )
        return (
            f"Set {service} in your environment"
            f" (for example: {example})"
            " or re-run 'nous provider add'"
        )
    return (
        f"Store the credential in the OS secret store for {service}/{account}"
        " (requires the optional 'keyring' package) or re-run 'nous provider add'"
    )


def _parse_reference(reference: str) -> tuple[str, str, str]:
    if reference.startswith("env:"):
        try:
            name = validate_environment_variable_name(reference[4:])
        except ValueError as exc:
            raise ValueError(
                "Invalid environment-variable reference. The configured name is "
                "malformed; re-create the provider with 'nous provider add', "
                "then run 'nous provider doctor'."
            ) from exc
        return "env", name, ""
    for prefix in ("secret:", "keyring:", "credman:"):
        if reference.startswith(prefix):
            value = reference[len(prefix) :]
            service, separator, account = value.partition(":")
            if not separator:
                service, separator, account = value.partition("/")
            if not service or not separator or not account:
                raise ValueError("Secret-store references require service and account")
            return "secret", service, account
    raise ValueError("Credential reference must use env:, secret:, keyring:, or credman:")


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise CredentialStoreUnavailable(
            "OS secret store support requires the optional 'keyring' package"
        ) from exc
    return keyring