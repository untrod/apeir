"""Bounded saved-file inputs for the existing Context and Governance owners.

Selecting a reference expresses intent. It never supplies read or Provider
transfer permission. The caller must keep this reader private and revalidate
inside the Gateway's actual Provider invocation boundary, including retries.
"""

from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit

from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.workspace.isolation import (
    WorkspaceFileChangedError,
    WorkspaceHardLinkError,
    read_workspace_bytes,
)
from nous_runtime.context.exceptions import ContextPermissionError
from nous_runtime.context.models import ContextItem, ContextSnapshot
from nous_runtime.context.security import ContextAccessRequest, ContextGuard
from nous_runtime.core.redaction import redact_sensitive_data, redact_sensitive_text
from nous_runtime.governance.contracts import ActionProposal, AuthorizationContext
from nous_runtime.governance.permission import PermissionEngine, PermissionRequest
from nous_runtime.workspace.workbench import _CODE_SUFFIXES

MAX_REFERENCES = 8
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 128 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SUFFIXES = frozenset(_CODE_SUFFIXES) | {".log", ".csv"}
_PRIVATE_PARTS = frozenset(
    {".nous", ".git", ".ssh", ".aws", ".azure", ".config", "private", "secrets"}
)
_SECRET_NAME = re.compile(
    r"(?:^|[._-])(?:secret|secrets|credentials|password|token|private[_-]?key)(?:[._-]|$)",
    re.IGNORECASE,
)
_SENSITIVE_DECLARATION = re.compile(
    r"(?im)(?:^|[\s\"'])(?:password|api[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key)"
    r"[\"']?\s*[:=]\s*\S+|-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)


class SelectedInputError(ContextPermissionError):
    """A safe source-input rejection without a raw path or source body."""


@dataclass(frozen=True)
class WorkspaceFileReference:
    """Exact saved source version; no content, permission, or host path."""

    path: str
    sha256: str

    def __post_init__(self):
        if (
            not isinstance(self.path, str)
            or not self.path
            or len(self.path) > 512
            or any(ord(char) < 32 for char in self.path)
            or "\\" in self.path
            or ":" in self.path
            or PureWindowsPath(self.path).drive
            or PurePosixPath(self.path).is_absolute()
            or any(part in {"", ".", ".."} for part in self.path.split("/"))
            or PurePosixPath(self.path).as_posix() != self.path
        ):
            raise SelectedInputError("invalid_relative_reference")
        parts = PurePosixPath(self.path).parts
        if (
            any(part.casefold() in _PRIVATE_PARTS for part in parts)
            or any(part.casefold().startswith(".env") for part in parts)
            or any(_SECRET_NAME.search(part) for part in parts)
            or PurePosixPath(self.path).suffix.casefold() not in _SUFFIXES
        ):
            raise SelectedInputError("unsupported_or_private_source")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise SelectedInputError("invalid_source_version")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkspaceFileReference:
        if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
            raise SelectedInputError("invalid_reference_fields")
        return cls(path=value["path"], sha256=value["sha256"])

    @property
    def source_id(self) -> str:
        # Inspectors and general telemetry retain a stable opaque reference.
        return "workspace-file:" + hashlib.sha256(self.path.encode()).hexdigest()


@dataclass(frozen=True)
class ProviderRecipient:
    """Actual Gateway candidate endpoint and transport, never a Provider alias."""

    provider_id: str
    endpoint: str
    transport: str

    def __post_init__(self):
        values = (self.provider_id, self.endpoint, self.transport)
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 2048
            or any(ord(char) < 32 for char in value)
            or redact_sensitive_text(value) != value
            for value in values
        ):
            raise SelectedInputError("provider_recipient_required")
        try:
            endpoint = urlsplit(self.endpoint)
            if (
                endpoint.scheme not in {"http", "https", "local", "mock"}
                or not endpoint.netloc
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise SelectedInputError("provider_endpoint_invalid")
        except ValueError:
            raise SelectedInputError("provider_endpoint_invalid") from None

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "provider_id": self.provider_id,
                    "endpoint": self.endpoint,
                    "transport": self.transport,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()


class SelectedWorkspaceInput:
    """Read selected files into ContextItems with independent fresh admission.

    This leaf does not register capabilities, grant permissions, create Work,
    call Providers, or persist source bodies. ``work_id`` binds the existing
    caller-owned Work/request identity; its existence remains that owner's job.
    """

    source_type = "project"

    def __init__(
        self,
        workspace: str | Path,
        references: Sequence[WorkspaceFileReference],
        *,
        authorization_context: AuthorizationContext,
        purpose: str,
        work_id: str,
        gate: Any,
    ):
        if (
            not isinstance(references, (list, tuple))
            or not references
            or len(references) > MAX_REFERENCES
            or any(not isinstance(ref, WorkspaceFileReference) for ref in references)
            or len({ref.path for ref in references}) != len(references)
        ):
            raise SelectedInputError("invalid_reference_count")
        if (
            not isinstance(authorization_context, AuthorizationContext)
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 1024
            or not isinstance(work_id, str)
            or not work_id.strip()
            or len(work_id) > 256
        ):
            raise SelectedInputError("missing_input_binding")
        try:
            self._root = Path(workspace).resolve(strict=True)
        except (OSError, TypeError, ValueError):
            raise SelectedInputError("invalid_workspace") from None
        if not self._root.is_dir() or any(
            (self._root / ".nous" / part).is_symlink()
            for part in ("", "context.db", "governance.db")
        ):
            raise SelectedInputError("invalid_workspace")
        if (
            not isinstance(getattr(gate, "permission_engine", None), PermissionEngine)
            or Path(gate.store.db_path).resolve()
            != self._root / ".nous" / "governance.db"
        ):
            raise SelectedInputError("configured_workspace_authority_required")
        self._gate = gate
        self._guard = ContextGuard(str(self._root), gate=gate)
        self._paths = WorkspaceGuard(str(self._root), protect_runtime_state=True)
        self._references = tuple(references)
        self._context = authorization_context
        self._purpose = purpose
        self._work_id = work_id
        self._workspace_resource = (
            "workspace:" + hashlib.sha256(str(self._root).encode()).hexdigest()
        )
        self._actor_type = {
            "user": "user",
            "agent": "agent",
            "service": "system",
            "automation": "system",
        }.get(authorization_context.subject_type, "")
        self._items: tuple[ContextItem, ...] = ()
        self._states = {ref.source_id: "selected" for ref in self._references}
        self._was_read = {ref.source_id: False for ref in self._references}
        self._audit("selected")

    def _binding(self, reference: WorkspaceFileReference) -> dict[str, str]:
        return {
            "source_id": reference.source_id,
            "source_version": reference.sha256,
            "workspace": str(self._root),
            "relative_path": reference.path,
            "subject_id": self._context.subject_id,
            "subject_type": self._context.subject_type,
            "authorization_context_id": self._context.context_id,
            "purpose_sha256": hashlib.sha256(self._purpose.encode()).hexdigest(),
            "work_id": self._work_id,
        }

    def _admit(
        self,
        reference: WorkspaceFileReference,
        recipient: ProviderRecipient | None = None,
    ):
        # Reconstruct to detect a corrupted reference before any read.
        WorkspaceFileReference(reference.path, reference.sha256)
        if (
            any(
                (self._root / ".nous" / part).is_symlink()
                for part in ("", "context.db", "governance.db")
            )
            or Path(self._gate.store.db_path).resolve()
            != self._root / ".nous" / "governance.db"
        ):
            raise SelectedInputError("configured_workspace_authority_required")
        access = self._guard.authorize(
            ContextAccessRequest(
                actor=self._context.subject_id,
                actor_type=self._actor_type,
                context_id=reference.source_id,
                purpose=self._purpose,
                requested_sources=(self.source_type,),
                authorization_context=self._context,
            )
        )
        if not access.allowed or self.source_type not in access.granted_sources:
            raise SelectedInputError("context_read_denied")
        if not isinstance(self._gate.permission_engine, PermissionEngine):
            raise SelectedInputError("configured_workspace_authority_required")
        permission_context = {
            **self._binding(reference),
            "action_type": "context_transfer" if recipient else "context_file_read",
        }
        scoped_read = self._gate.permission_engine.check(
            PermissionRequest(
                subject=self._context.subject_id,
                action="workspace.read",
                resource=self._workspace_resource,
                context=permission_context,
            )
        )
        if scoped_read.allowed is not True:
            raise SelectedInputError("workspace_read_denied")
        if recipient:
            # Gate's compatibility permission context has no recipient field.
            # Reuse its canonical engine for an exact source+recipient resource
            # as well; a read grant alone cannot transfer to any Provider.
            transfer = self._gate.permission_engine.check(
                PermissionRequest(
                    subject=self._context.subject_id,
                    action="context.transfer",
                    resource=self.transfer_resource(recipient),
                    context={
                        **permission_context,
                        "provider_id": recipient.provider_id,
                        "recipient_sha256": recipient.digest,
                    },
                )
            )
            if transfer.allowed is not True:
                raise SelectedInputError("provider_transfer_denied")
        proposal = ActionProposal(
            capability_id="context.read",
            action_type="context_transfer" if recipient else "context_file_read",
            agent_id=self._context.subject_id if self._actor_type == "agent" else "",
            target_workspace=str(self._root),
            locality=self._context.session_locality,
            affected_resources=(self._workspace_resource,),
            params={
                **self._binding(reference),
                "recipient_sha256": recipient.digest if recipient else "",
            },
            parameter_summary="Use the exact selected saved-file input",
            # The scoped workspace/transfer checks above use the same canonical
            # engine with source bindings. Gate's compatibility context lacks
            # those fields, so it independently revalidates context permission.
            required_permissions=("context.read",),
            external_recipients=(recipient.endpoint,) if recipient else (),
            data_classification="internal",
            side_effect_class="read_only",
            reversibility="reversible",
            retry_behavior="idempotent",
        )
        decision = self._gate.evaluate(proposal, self._context)
        persisted = self._gate.store.get_decision(decision.decision_id)
        if (
            decision.allowed is not True
            or decision.action_mode != "EXECUTE"
            or not isinstance(persisted, dict)
            or any(
                persisted.get(key) != value
                for key, value in {
                    "allowed": True,
                    "action_mode": "EXECUTE",
                    "decision_id": decision.decision_id,
                    "proposal_hash": proposal.proposal_hash,
                    "context_id": self._context.context_id,
                }.items()
            )
        ):
            raise SelectedInputError(
                "provider_transfer_denied" if recipient else "workspace_read_denied"
            )

    def transfer_resource(self, recipient: ProviderRecipient) -> str:
        return self._workspace_resource + ":provider:" + recipient.digest

    def binding_digest(self, reference: WorkspaceFileReference) -> str:
        return hashlib.sha256(
            json.dumps(
                self._binding(reference), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def _read(
        self, reference: WorkspaceFileReference, *, byte_limit: int = MAX_FILE_BYTES
    ) -> bytes:
        """Open each component with no-follow descriptors; unsupported hosts deny.

        WorkspaceGuard remains the canonical path boundary. Descriptor traversal
        additionally prevents symlink replacement between validation and read.
        """
        try:
            self._paths.validate_path(reference.path)
        except ValueError as exc:
            if isinstance(exc.__cause__, WorkspaceHardLinkError):
                raise SelectedInputError("source_link_refused") from None
            raise
        if (
            os.open not in os.supports_dir_fd
            or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")
        ):
            raise SelectedInputError("safe_source_read_unavailable")
        try:

            def mark_read():
                self._was_read[reference.source_id] = True

            data = read_workspace_bytes(
                self._root,
                reference.path,
                max_bytes=min(byte_limit, MAX_FILE_BYTES),
                minimum_bytes=1,
                follow_internal_links=False,
                on_read=mark_read,
            )
            if hashlib.sha256(data).hexdigest() != reference.sha256:
                raise SelectedInputError("source_version_changed")
            content = data.decode("utf-8", errors="strict")
            if any(
                (ord(char) < 32 and char not in "\n\r\t") or 127 <= ord(char) < 160
                for char in content
            ):
                raise SelectedInputError("binary_source_refused")
            if redact_sensitive_text(
                content
            ) != content or _SENSITIVE_DECLARATION.search(content):
                raise SelectedInputError("secret_source_refused")
            if PurePosixPath(reference.path).suffix.casefold() == ".json":
                parsed = json.loads(content)
                if redact_sensitive_data(parsed) != parsed:
                    raise SelectedInputError("secret_source_refused")
            if PurePosixPath(reference.path).suffix.casefold() == ".csv":
                headers = next(csv.reader(io.StringIO(content)), [])
                classification = {header: "selected_value" for header in headers}
                if redact_sensitive_data(classification) != classification:
                    raise SelectedInputError("secret_source_refused")
            return data
        except SelectedInputError:
            raise
        except WorkspaceHardLinkError:
            raise SelectedInputError("source_link_refused") from None
        except WorkspaceFileChangedError:
            raise SelectedInputError("source_version_changed") from None
        except (OSError, ValueError, UnicodeError):
            raise SelectedInputError("source_unavailable_or_invalid") from None

    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < len(self._references)
        ):
            raise SelectedInputError("reference_item_bound")
        items = []
        total = 0
        try:
            for reference in self._references:
                self._admit(reference)
                data = self._read(reference, byte_limit=MAX_TOTAL_BYTES - total)
                total += len(data)
                if total > MAX_TOTAL_BYTES:
                    raise SelectedInputError("aggregate_source_byte_bound")
                self._states[reference.source_id] = "read"
                self._audit("read")
                # A revocation during filesystem access must prevent delivery.
                self._admit(reference)
                items.append(
                    ContextItem(
                        item_id="selected_" + reference.source_id.split(":", 1)[1],
                        source_type=self.source_type,
                        source_id=reference.source_id,
                        content=data.decode("utf-8"),
                        importance=1.0,
                        confidence=1.0,
                        metadata={
                            "context_class": "workspace_facts",
                            "source_version": reference.sha256,
                            "file_sha256": reference.sha256,
                            "selected_input": True,
                            "work_id": self._work_id,
                            "selected_input_binding_sha256": self.binding_digest(
                                reference
                            ),
                            "size_bytes": len(data),
                        },
                    )
                )
                self._states[reference.source_id] = "read"
            self._items = tuple(items)
            self._audit("read")
            return items
        except Exception as exc:
            self._items = ()
            self._states = {ref.source_id: "rejected" for ref in self._references}
            self._audit("rejected")
            if isinstance(exc, SelectedInputError):
                raise
            raise SelectedInputError("selected_input_unavailable") from None

    def authorize_transfer(
        self, snapshot: ContextSnapshot, recipient: ProviderRecipient
    ) -> None:
        """Call immediately before *every* actual Provider attempt.

        Authorization does not prove that the Provider received the request.
        The Gateway owner must record actual dispatch separately.
        """
        if not isinstance(recipient, ProviderRecipient):
            raise SelectedInputError("provider_recipient_required")
        selected = {item.item_id: item for item in snapshot.items}
        try:
            if not self._items:
                raise SelectedInputError("selected_input_not_collected")
            expected_ids = {item.item_id for item in self._items}
            if len(selected) != len(snapshot.items) or any(
                item.metadata.get("selected_input") and item.item_id not in expected_ids
                for item in snapshot.items
            ):
                raise SelectedInputError("selected_input_changed")
            omissions = {
                item.get("item_id")
                for item in snapshot.metadata.get("truncation_explanation", [])
                if item.get("included_characters") == 0
                and item.get("reason")
                in {
                    "context_item_budget",
                    "context_input_token_budget",
                    "context_class_token_budget",
                }
            }
            for item, reference in zip(self._items, self._references, strict=True):
                included = selected.get(item.item_id)
                if included is None:
                    if item.item_id not in omissions:
                        raise SelectedInputError("selected_input_changed")
                    self._states[reference.source_id] = "budget_limited"
                    continue
                if (
                    included.content != item.content
                    or included.source_id != item.source_id
                    or included.source_version != reference.sha256
                    or included.permission != item.permission
                    or included.metadata.get("selected_input_binding_sha256")
                    != self.binding_digest(reference)
                ):
                    raise SelectedInputError("selected_input_changed")
                self._admit(reference, recipient)
                if self._read(reference).decode("utf-8") != item.content:
                    raise SelectedInputError("source_version_changed")
                self._admit(reference, recipient)
                self._states[reference.source_id] = "transfer_admitted"
            self._audit("transfer_admitted")
        except Exception as exc:
            self._states = {ref.source_id: "rejected" for ref in self._references}
            self._audit("rejected")
            if isinstance(exc, SelectedInputError):
                raise
            raise SelectedInputError("selected_input_unavailable") from None

    def provenance(self) -> list[dict[str, str | bool]]:
        return [
            {
                "source_id": ref.source_id,
                "source_version": ref.sha256,
                "status": self._states[ref.source_id],
                "was_read": self._was_read[ref.source_id],
            }
            for ref in self._references
        ]

    def require_collected(self) -> None:
        if not self._items or any(state != "read" for state in self._states.values()):
            raise SelectedInputError("selected_input_not_collected")

    def reject(self) -> list[dict[str, str | bool]]:
        self._states = {ref.source_id: "rejected" for ref in self._references}
        return self.provenance()

    def prepare_snapshot(self, snapshot: ContextSnapshot) -> None:
        included = {item.item_id for item in snapshot.items}
        omitted = {
            item.get("item_id")
            for item in snapshot.metadata.get("truncation_explanation", [])
            if item.get("included_characters") == 0
            and item.get("reason")
            in {
                "context_item_budget",
                "context_input_token_budget",
                "context_class_token_budget",
            }
        }
        for item, reference in zip(self._items, self._references, strict=True):
            if item.item_id not in included:
                if item.item_id not in omitted:
                    raise SelectedInputError("selected_input_changed")
                self._states[reference.source_id] = "budget_limited"

    def mark_dispatched(self) -> None:
        # This records the Gateway's Provider boundary, not Provider receipt.
        self._states = {
            source: "sent" if state == "transfer_admitted" else state
            for source, state in self._states.items()
        }
        self._audit("sent")

    def _audit(self, state: str):
        if any(
            (self._root / ".nous" / part).is_symlink() for part in ("", "context.db")
        ):
            raise SelectedInputError("selected_input_audit_unavailable")

        if not self._guard._store.record_audit(
            snapshot_id="selected-input:"
            + hashlib.sha256(self._work_id.encode()).hexdigest(),
            actor=self._context.subject_id,
            purpose="selected_input_" + state,
            decision="deny" if state == "rejected" else "allow",
            metadata={
                "work_id": self._work_id,
                "purpose_sha256": hashlib.sha256(self._purpose.encode()).hexdigest(),
                "sources": self.provenance(),
                "execution_authority": False,
            },
        ):
            raise SelectedInputError("selected_input_audit_unavailable")


class SelectedInputAdmission:
    """Private per-invocation input binding; never part of a serialized request."""

    def __init__(
        self, reader, snapshot, verify_original, messages, tools, *, emit=None
    ):
        self.reader = reader
        self.snapshot = snapshot
        self.verify_original = verify_original
        self.input_sha256 = self._digest(messages, tools)
        self.emit = emit
        self.last_evidence = {}
        self.recipient_sha256 = ""

    @staticmethod
    def _digest(messages, tools):
        return hashlib.sha256(
            json.dumps(
                {"messages": list(messages), "tools": list(tools)},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

    def __call__(self, request, recipient):
        try:
            if (
                not self.verify_original()
                or self._digest(request.messages, request.metadata.get("tools") or ())
                != self.input_sha256
            ):
                raise SelectedInputError("original_request_or_input_changed")
            self.reader.authorize_transfer(self.snapshot, recipient)
            self.recipient_sha256 = recipient.digest
            return {
                "input_sha256": self.input_sha256,
                "sources": self.reader.provenance(),
                "recipient_sha256": recipient.digest,
                "scope": "gateway-provider-dispatch",
                "provider_receipt_confirmed": False,
            }
        except Exception:
            self.reader._states = {
                ref.source_id: "rejected" for ref in self.reader._references
            }
            if self.emit is not None:
                self.emit(
                    "context.input.rejected",
                    {
                        "input_sha256": self.input_sha256,
                        "sources": self.reader.provenance(),
                    },
                )
            raise SelectedInputError("selected_input_dispatch_denied") from None

    def dispatched(self):
        self.reader.mark_dispatched()
        evidence = {
            "input_sha256": self.input_sha256,
            "sources": self.reader.provenance(),
            "recipient_sha256": self.recipient_sha256,
            "scope": "gateway-provider-dispatch",
            "provider_receipt_confirmed": False,
        }
        if self.emit is not None:
            self.emit("context.input.dispatched", evidence)
        self.last_evidence = evidence
        return evidence
