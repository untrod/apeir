"""Operation-scoped delivery of existing SecretRef values under the canonical Gate."""

from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from nous_runtime.core.redaction import (
    redact_sensitive_data,
    redact_sensitive_text,
    register_sensitive_value,
)
from nous_runtime.governance.contracts import AuthorizationContext, _new_id
from nous_runtime.governance import operation_gate
from nous_runtime.kernel.identity import SecretRef
from nous_runtime.security.private_files import restrict_owner_only_file
from nous_runtime.security.vault import SecretVault

# Reuse Kernel's nonsecret reference contract without changing Kernel.
SecretHandle = SecretRef
_HANDLE = re.compile(r"^secret_[a-f0-9]{32}$")


def validate_secret_handles(handles) -> tuple[str, ...]:
    if (
        not isinstance(handles, (list, tuple))
        or any(
            not isinstance(item, str) or not _HANDLE.fullmatch(item) for item in handles
        )
        or len(set(handles)) != len(handles)
    ):
        raise ValueError("SecretHandle references must be unique opaque identifiers")
    return tuple(handles)


class SecretBackend(Protocol):
    """Protected storage interface. Only CredentialBroker receives this interface."""

    def resolve(self, handle: SecretHandle) -> str: ...


class VaultSecretBackend:
    """Adapt the existing AES-GCM vault; require an explicit stable master key."""

    def __init__(self, db_path, *, master_key: bytes):
        if len(master_key) != 32:
            raise ValueError("A stable 256-bit vault master key is required")
        self._vault = SecretVault(str(db_path), master_key=master_key)
        restrict_owner_only_file(db_path, subject="SecretBackend")

    def put(self, handle_id: str, value: str) -> SecretHandle:
        validate_secret_handles((handle_id,))
        register_sensitive_value(value)
        result = self._vault.put(handle_id, value, created_by="credential-owner")
        if not result.ok:
            raise RuntimeError("Secret backend write failed")
        return result.value

    def resolve(self, handle: SecretHandle) -> str:
        result = self._vault.get(handle.vault_path)
        if not result.ok:
            raise PermissionError("Secret backend value unavailable")
        register_sensitive_value(result.value)
        return result.value


class ReferenceSecretBackend:
    """Protected aliases to existing environment/OS-keyring references."""

    def __init__(self, references: dict[str, str]):
        validate_secret_handles(tuple(references))
        self._references = dict(references)

    def resolve(self, handle: SecretHandle) -> str:
        from nous_runtime.provider.credentials import resolve_credential

        reference = self._references.get(handle.vault_path)
        if not reference:
            raise PermissionError("Secret backend value unavailable")
        value = resolve_credential(reference)
        if not value:
            raise PermissionError("Secret backend value unavailable")
        register_sensitive_value(value)
        return value


@dataclass(frozen=True)
class CredentialLease:
    """Delivery evidence only: this lease never authorizes an Operation effect."""

    lease_id: str
    authorization_id: str
    authorization_context_id: str
    handle_id: str
    subject_id: str
    work_id: str
    operation_id: str
    node_id: str
    capability_id: str
    resource_id: str
    expires_at: str
    status: str = "ACTIVE"

    def to_dict(self):
        return asdict(self)


class CredentialContext:
    """Transient provider input. It cannot be serialized, cached or reused."""

    _sensitive_execution_context = True

    def __init__(self, leases, values, revalidate):
        self.leases = tuple(leases)
        self._values = values
        self._revalidate = revalidate
        self._active = True

    def __repr__(self):
        return "CredentialContext(<REDACTED>)"

    def __reduce__(self):
        raise TypeError("CredentialContext is execution-only")

    def get(self, handle_id: str) -> str:
        self.revalidate()
        if handle_id not in self._values:
            raise PermissionError("CredentialContext scope mismatch")
        return self._values[handle_id]

    def revalidate(self):
        if not self._active:
            raise PermissionError("CredentialContext is closed")
        self._revalidate()

    def close(self):
        self._active = False
        self._values.clear()


class CredentialBroker:
    """Credential delivery, not a second execution or authorization authority."""

    def __init__(self, gate, backend: SecretBackend | None = None, *, lease_seconds=30):
        if not 0 < lease_seconds <= 300:
            raise ValueError("Credential lease expiry must be explicitly bounded")
        self.gate = gate
        self._backend = backend
        self.lease_seconds = lease_seconds

    def register_handle(
        self,
        handle: SecretHandle,
        authorization_id: str,
        context: AuthorizationContext,
        *,
        validity_seconds=3600,
    ):
        request = self.gate.get_operation_request(authorization_id)
        self.gate._require_human(context, request)
        validate_secret_handles((handle.vault_path,))
        if handle.vault_path not in request.secret_handles:
            raise PermissionError("SecretHandle is not declared by the Operation")
        if not 0 < validity_seconds <= 86400:
            raise ValueError("SecretHandle expiry must be bounded")
        bindings = {
            key: getattr(request, key)
            for key in ("node_id", "capability_id", "resource_id", "subject_id")
        }
        reference = {"vault_path": handle.vault_path, "key_id": handle.key_id}
        if redact_sensitive_data(reference) != reference:
            raise ValueError("SecretHandle metadata must not contain secret material")
        expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=validity_seconds)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.gate.store.operation_transaction() as db:
            if self.gate._revoked(db, handle.vault_path):
                raise PermissionError("SecretHandle remains revoked")
            prior = db.execute(
                "SELECT reference_json,bindings_json FROM governance_secret_handles WHERE handle_id=?",
                (handle.vault_path,),
            ).fetchone()
            if prior and (
                json.loads(prior[0]) != reference or json.loads(prior[1]) != bindings
            ):
                raise PermissionError("SecretHandle binding cannot change")
            db.execute(
                "INSERT OR REPLACE INTO governance_secret_handles VALUES(?,?,?,?,?)",
                (
                    handle.vault_path,
                    json.dumps(reference),
                    json.dumps(bindings),
                    expiry,
                    "ACTIVE",
                ),
            )
            self.gate.store.append_operation_audit(
                db,
                "credential.handle.registered",
                self.gate._evidence(
                    request,
                    secret_handle=handle.vault_path,
                    actor_id=context.subject_id,
                    authorization_context_id=context.context_id,
                ),
            )

    def revoke(self, authorization_id, context, *, handle_id="", lease_id=""):
        request = self.gate.get_operation_request(authorization_id)
        self.gate._require_human(context, request)
        if bool(handle_id) == bool(lease_id):
            raise ValueError("One credential revocation target is required")
        with self.gate.store.operation_transaction() as db:
            if handle_id:
                validate_secret_handles((handle_id,))
                if handle_id not in request.secret_handles:
                    raise PermissionError("SecretHandle scope mismatch")
                db.execute(
                    "UPDATE governance_secret_handles SET status='REVOKED' WHERE handle_id=?",
                    (handle_id,),
                )
                from nous_runtime.governance.contracts import RevocationRecord

                revocation = RevocationRecord(
                    target_type="secret",
                    target_id=handle_id,
                    revoked_by=context.subject_id,
                )
                db.execute(
                    "INSERT INTO governance_revocations (revocation_id,target_type,target_id,revoked_by,revocation_json) VALUES(?,?,?,?,?)",
                    (
                        revocation.revocation_id,
                        "secret",
                        handle_id,
                        context.subject_id,
                        json.dumps(revocation.to_dict()),
                    ),
                )
            else:
                row = db.execute(
                    "SELECT authorization_id FROM governance_credential_leases WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
                if not row or row[0] != authorization_id:
                    raise PermissionError("CredentialLease scope mismatch")
                db.execute(
                    "UPDATE governance_credential_leases SET status='REVOKED' WHERE lease_id=?",
                    (lease_id,),
                )
            self.gate.store.append_operation_audit(
                db,
                "credential.revoked",
                self.gate._evidence(
                    request,
                    secret_handle=handle_id,
                    credential_lease_id=lease_id,
                    actor_id=context.subject_id,
                ),
            )

    def _admission(self, authorization_id, context, admission):
        record = self.gate._execution_admissions.get(admission)
        if not record or record[0] != authorization_id or record[1] is not context:
            raise PermissionError(
                "Credential resolution requires active Node admission"
            )
        admission()
        return record[2], self.gate.get_operation_request_from_admission(admission)

    def _handle(self, db, request, handle_id):
        row = db.execute(
            "SELECT * FROM governance_secret_handles WHERE handle_id=?", (handle_id,)
        ).fetchone()
        if (
            not row
            or row["status"] != "ACTIVE"
            or row["expires_at"] <= operation_gate._utc_now()
            or self.gate._revoked(db, handle_id)
        ):
            raise PermissionError("SecretHandle is missing, expired or revoked")
        expected = {
            key: getattr(request, key)
            for key in ("node_id", "capability_id", "resource_id", "subject_id")
        }
        if json.loads(row["bindings_json"]) != expected:
            raise PermissionError("SecretHandle scope mismatch")
        return row

    @contextlib.contextmanager
    def execution(self, authorization_id, context: AuthorizationContext, *, admission):
        if self._backend is None:
            raise PermissionError("Secret backend is unavailable")
        db, request = self._admission(authorization_id, context, admission)
        handles = validate_secret_handles(request.secret_handles)
        if not handles:
            raise PermissionError("Operation declares no SecretHandle")
        leases = []
        values = {}
        persisted = False
        try:
            for handle_id in handles:
                row = self._handle(db, request, handle_id)
                expiry = min(
                    row["expires_at"],
                    (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=self.lease_seconds)
                    ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
                grant = self.gate._matching_grant(db, request, admitted=True)
                if grant:
                    expiry = min(expiry, grant["expires_at"])
                lease = CredentialLease(
                    _new_id("cred"),
                    authorization_id,
                    context.context_id,
                    handle_id,
                    context.subject_id,
                    request.work_id,
                    request.operation_id,
                    request.node_id,
                    request.capability_id,
                    request.resource_id,
                    expiry,
                )
                try:
                    db.execute(
                        "INSERT INTO governance_credential_leases VALUES(?,?,?,?,?,?)",
                        (
                            lease.lease_id,
                            authorization_id,
                            handle_id,
                            expiry,
                            "ACTIVE",
                            json.dumps(lease.to_dict()),
                        ),
                    )
                except Exception:
                    raise PermissionError(
                        "CredentialLease cannot be issued again"
                    ) from None
                leases.append(lease)
                self.gate.store.append_operation_audit(
                    db,
                    "credential.lease.issued",
                    self.gate._evidence(
                        request,
                        **{
                            "credential_lease_id": lease.lease_id,
                            "secret_handle": handle_id,
                            "authorization_context_id": context.context_id,
                        },
                    ),
                )
            # Commit delivery evidence before resolution/effect. Reacquire the same
            # governance fence and revalidate after this transaction boundary.
            db.commit()
            persisted = True
            db.execute("BEGIN IMMEDIATE")
            admission()
            for handle_id in handles:
                row = self._handle(db, request, handle_id)
                try:
                    value = self._backend.resolve(
                        SecretHandle(**json.loads(row["reference_json"]))
                    )
                    if not isinstance(value, str) or not value:
                        raise ValueError()
                    register_sensitive_value(value)
                    values[handle_id] = value
                except Exception:
                    raise PermissionError("Secret backend resolution failed") from None

            def revalidate():
                admission()
                for lease in leases:
                    row = db.execute(
                        "SELECT status,expires_at FROM governance_credential_leases WHERE lease_id=?",
                        (lease.lease_id,),
                    ).fetchone()
                    if (
                        not row
                        or row[0] != "ACTIVE"
                        or row[1] <= operation_gate._utc_now()
                    ):
                        raise PermissionError(
                            "CredentialLease is expired, revoked or closed"
                        )
                    self._handle(db, request, lease.handle_id)

            execution = CredentialContext(leases, values, revalidate)
            try:
                revalidate()
                yield execution
            finally:
                execution.close()
        finally:
            values.clear()
            # Node's journal/unique delivery binding, not this cleanup, fences
            # uncertain effects. Cleanup failure must not replace effect evidence.
            if persisted:
                import sqlite3

                try:
                    for lease in leases:
                        db.execute(
                            "UPDATE governance_credential_leases SET status='CLOSED' WHERE lease_id=? AND status='ACTIVE'",
                            (lease.lease_id,),
                        )
                        self.gate.store.append_operation_audit(
                            db,
                            "credential.lease.closed",
                            self.gate._evidence(
                                request,
                                credential_lease_id=lease.lease_id,
                                secret_handle=lease.handle_id,
                            ),
                        )
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
                except sqlite3.Error:
                    import logging

                    logging.getLogger("nous.governance.credentials").warning(
                        "Credential delivery cleanup failed; persisted delivery remains fenced"
                    )

    def run_provider(self, authorization_id, context, *, admission, call):
        from nous_runtime.node_runtime.service import WorkloadResponseLost

        with self.execution(
            authorization_id, context, admission=admission
        ) as credentials:
            stdout, stderr = io.StringIO(), io.StringIO()
            try:
                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    result = call(credentials)
                safe = redact_sensitive_data(result)
                if isinstance(safe, dict):
                    safe["credential_lease_ids"] = [
                        lease.lease_id for lease in credentials.leases
                    ]
                return safe
            except WorkloadResponseLost as exc:
                output = redact_sensitive_data(exc.output)
                output["credential_lease_ids"] = [
                    lease.lease_id for lease in credentials.leases
                ]
                raise WorkloadResponseLost(
                    redact_sensitive_text(str(exc)),
                    output=output,
                    completed=exc.completed,
                ) from None
            except Exception as exc:
                raise RuntimeError(redact_sensitive_text(str(exc))) from None
            finally:
                # Captured output never becomes an ordinary Event/Receipt buffer.
                import sys

                sys.stdout.write(redact_sensitive_text(stdout.getvalue()))
                sys.stderr.write(redact_sensitive_text(stderr.getvalue()))
