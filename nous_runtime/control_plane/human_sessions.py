"""OIDC/PKCE human authentication at the existing Governance boundary.

Identity is established by an explicitly configured external identity provider.
This module owns authentication evidence, not permission or execution authority.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from weakref import WeakValueDictionary, finalize

from nous_runtime.core.redaction import register_sensitive_value
from nous_runtime.governance.contracts import AuthorizationContext
from nous_runtime.governance.permission import (
    PermissionEngine,
    PermissionRequest,
    PermissionRule,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def request_digest(method: str, path: str, body) -> str:
    return _digest(
        json.dumps(
            [method.upper(), path, body or {}], sort_keys=True, separators=(",", ":")
        )
    )


@dataclass(frozen=True)
class HumanIdentity:
    subject_id: str
    issuer: str
    expires_at: int
    methods: tuple[str, ...]


class HumanIdentityProvider(Protocol):
    """External identity adapter; configured by the trusted host owner only."""

    issuer: str
    client_id: str
    redirect_uri: str
    authorization_endpoint: str

    def authenticate(
        self, code: str, verifier: str, nonce_digest: str
    ) -> HumanIdentity: ...


class OIDCHumanIdentityProvider:
    """Use Authlib OAuth2 and PyJWT verification, not a local identity system."""

    def __init__(self, config: dict, *, jwk_client=None, oauth_client=None):
        import jwt

        required = (
            "issuer",
            "client_id",
            "redirect_uri",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "subjects",
        )
        if any(not config.get(key) for key in required):
            raise ValueError("Trusted OIDC configuration is incomplete")
        for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = urlsplit(config[key])
            if (
                value.scheme != "https"
                or not value.hostname
                or value.username
                or value.password
            ):
                raise ValueError("OIDC endpoints must use authenticated HTTPS")
        redirect = urlsplit(config["redirect_uri"])
        if redirect.scheme != "https" and not (
            redirect.scheme == "http"
            and redirect.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("OIDC callback requires HTTPS or loopback")
        self.issuer = config["issuer"]
        self.client_id = config["client_id"]
        self.redirect_uri = config["redirect_uri"]
        self.authorization_endpoint = config["authorization_endpoint"]
        self.token_endpoint = config["token_endpoint"]
        self.subjects = frozenset(config["subjects"])
        self.required_methods = frozenset(config.get("required_methods", ["mfa"]))
        if (
            not self.required_methods
            or not self.subjects
            or not all(isinstance(item, str) and item for item in self.subjects)
        ):
            raise ValueError(
                "Explicit human subjects and authentication methods are required"
            )
        self._keys = jwk_client or jwt.PyJWKClient(config["jwks_uri"], timeout=5)
        self._oauth_client = oauth_client

    def authenticate(self, code, verifier, nonce_digest):
        import jwt
        from authlib.integrations.requests_client import OAuth2Session

        client = self._oauth_client or OAuth2Session(
            self.client_id,
            redirect_uri=self.redirect_uri,
            token_endpoint_auth_method="none",
        )
        try:
            token = client.fetch_token(
                self.token_endpoint,
                grant_type="authorization_code",
                code=code,
                code_verifier=verifier,
                timeout=5,
            )
            assertion = token["id_token"]
            register_sensitive_value(assertion)
            key = self._keys.get_signing_key_from_jwt(assertion).key
            claims = jwt.decode(
                assertion,
                key,
                algorithms=["RS256", "ES256", "EdDSA"],
                audience=self.client_id,
                issuer=self.issuer,
                options={"require": ["sub", "exp", "iat", "nonce", "auth_time", "amr"]},
            )
            methods = claims["amr"]
            now = int(time.time())
            if (
                claims["sub"] not in self.subjects
                or not isinstance(methods, list)
                or not self.required_methods.issubset(methods)
                or not hmac.compare_digest(_digest(claims["nonce"]), nonce_digest)
                or not isinstance(claims["auth_time"], (int, float))
                or not 0 <= now - claims["auth_time"] <= 300
                or (claims.get("azp") is not None and claims["azp"] != self.client_id)
                or (
                    isinstance(claims["aud"], list)
                    and len(claims["aud"]) > 1
                    and claims.get("azp") != self.client_id
                )
            ):
                raise ValueError("Identity proof does not establish an enrolled human")
            return HumanIdentity(
                "oidc:" + _digest(self.issuer)[:16] + ":" + claims["sub"],
                self.issuer,
                int(claims["exp"]),
                tuple(methods),
            )
        except Exception:
            raise PermissionError("Trusted human authentication failed") from None
        finally:
            if self._oauth_client is None:
                client.close()


_contexts: WeakValueDictionary[str, AuthorizationContext] = WeakValueDictionary()
_context_stores: dict[str, str] = {}
_context_permissions: dict[str, PermissionEngine] = {}


def human_permission(context, action, resource):
    policy = _context_permissions.get(getattr(context, "context_id", ""))
    return bool(
        policy
        and _contexts.get(context.context_id) is context
        and policy.check(
            PermissionRequest(
                context.subject_id, action, resource, {"subject_type": "user"}
            )
        ).allowed
    )


def is_human_session_context(context, store, *, db=None) -> bool:
    """Validate the actual nonserialized origin and durable current identity."""
    if (
        not isinstance(context, AuthorizationContext)
        or _contexts.get(context.context_id) is not context
        or _context_stores.get(context.context_id) != str(Path(store.db_path).resolve())
    ):
        return False

    def check(connection):
        row = connection.execute(
            "SELECT * FROM governance_human_sessions WHERE session_id=?",
            (context.session_id,),
        ).fetchone()
        return bool(
            row
            and row["status"] == "ACTIVE"
            and row["expires_at"] > int(time.time())
            and row["subject_id"] == context.subject_id
            and context.subject_type == "user"
            and context.authn_method == "oidc_pkce"
            and context.session_locality == "remote"
        )

    if db is not None:
        return check(db)
    with store.operation_transaction() as connection:
        return check(connection)


class AuthenticationResponse(dict):
    """Cookie material stays inside the HTTP authentication boundary, not JSON."""

    def __init__(self, data, *, cookie=None):
        super().__init__(ok=True, data=data)
        self.session_cookie = cookie


class HumanSessionAuth:
    def __init__(
        self,
        store,
        provider: HumanIdentityProvider,
        *,
        session_seconds=900,
        clock=time.time,
        permissions: PermissionEngine | None = None,
    ):
        if not 1 <= session_seconds <= 900:
            raise ValueError("Human sessions must expire within 15 minutes")
        self.store, self.provider = store, provider
        self.session_seconds, self.clock = session_seconds, clock
        self.permissions = permissions or PermissionEngine()

    def _audit(self, db, event, **evidence):
        self.store.append_operation_audit(
            db, event, {"schema": "apeir.human-auth/v1", **evidence}
        )

    def challenge(self, pkce_challenge: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", pkce_challenge):
            raise ValueError("S256 PKCE challenge is required")
        challenge_id, nonce = (
            "login_" + secrets.token_hex(16),
            secrets.token_urlsafe(32),
        )
        expiry = int(self.clock()) + 300
        with self.store.operation_transaction() as db:
            db.execute(
                "INSERT INTO governance_human_challenges VALUES(?,?,?,?,0)",
                (challenge_id, _digest(nonce), pkce_challenge, expiry),
            )
            self._audit(
                db,
                "human.challenge.issued",
                challenge_id=challenge_id,
                expires_at=expiry,
            )
        query = urlencode(
            {
                "client_id": self.provider.client_id,
                "redirect_uri": self.provider.redirect_uri,
                "response_type": "code",
                "scope": "openid profile",
                "state": challenge_id,
                "nonce": nonce,
                "code_challenge": pkce_challenge,
                "code_challenge_method": "S256",
                "max_age": 300,
            }
        )
        return {
            "challenge_id": challenge_id,
            "authorization_url": self.provider.authorization_endpoint + "?" + query,
            "expires_at": expiry,
        }

    def login(self, challenge_id: str, code: str, verifier: str):
        if (
            not isinstance(code, str)
            or not code
            or len(code) > 4096
            or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
        ):
            raise PermissionError("Invalid authentication proof")
        register_sensitive_value(code)
        register_sensitive_value(verifier)
        pkce = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        # Consume the challenge before calling the IdP. An uncertain login is
        # restarted with a fresh challenge; an authorization code is not replayed.
        with self.store.operation_transaction() as db:
            challenge = db.execute(
                "SELECT * FROM governance_human_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if (
                not challenge
                or challenge["consumed"]
                or challenge["expires_at"] <= int(self.clock())
                or not hmac.compare_digest(challenge["pkce_challenge"], pkce)
            ):
                raise PermissionError(
                    "Authentication challenge is expired, consumed or mismatched"
                )
            db.execute(
                "UPDATE governance_human_challenges SET consumed=1 WHERE challenge_id=?",
                (challenge_id,),
            )
            self._audit(db, "human.challenge.consumed", challenge_id=challenge_id)
        identity = self.provider.authenticate(code, verifier, challenge["nonce_digest"])
        now = int(self.clock())
        expiry = min(now + self.session_seconds, identity.expires_at)
        if expiry <= now or identity.issuer != self.provider.issuer:
            raise PermissionError("Identity proof is expired or untrusted")
        session_id, token = (
            "human_" + secrets.token_hex(16),
            "hums_" + secrets.token_urlsafe(32),
        )
        register_sensitive_value(token)
        with self.store.operation_transaction() as db:
            db.execute(
                "INSERT INTO governance_human_sessions VALUES(?,?,?,?,?,?,?)",
                (
                    session_id,
                    _digest(token),
                    identity.subject_id,
                    identity.issuer,
                    expiry,
                    "ACTIVE",
                    json.dumps({"methods": identity.methods}),
                ),
            )
            self._audit(
                db,
                "human.session.created",
                session_id=session_id,
                actor_id=identity.subject_id,
                issuer=identity.issuer,
                expires_at=expiry,
            )
        return AuthenticationResponse(
            {
                "session_id": session_id,
                "subject_id": identity.subject_id,
                "expires_at": expiry,
            },
            cookie=token,
        )

    def authenticate(self, token: str):
        with self.store.operation_transaction() as db:
            row = db.execute(
                "SELECT * FROM governance_human_sessions WHERE token_digest=?",
                (_digest(token),),
            ).fetchone()
            if (
                not row
                or row["status"] != "ACTIVE"
                or row["expires_at"] <= int(self.clock())
                or row["issuer"] != self.provider.issuer
            ):
                return None
        enrolled = getattr(self.provider, "subjects", None)
        if enrolled is not None and not any(
            row["subject_id"]
            == "oidc:"
            + hashlib.sha256(self.provider.issuer.encode()).hexdigest()[:16]
            + ":"
            + subject
            for subject in enrolled
        ):
            return None
        context = AuthorizationContext(
            subject_type="user",
            subject_id=row["subject_id"],
            authn_method="oidc_pkce",
            authn_confidence=1.0,
            session_id=row["session_id"],
            session_locality="remote",
        )
        _contexts[context.context_id] = context
        _context_stores[context.context_id] = str(Path(self.store.db_path).resolve())
        _context_permissions[context.context_id] = self.permissions
        finalize(context, _context_stores.pop, context.context_id, None)
        finalize(context, _context_permissions.pop, context.context_id, None)
        return context

    def nonce(self, context, method: str, path: str, body):
        if (
            method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}
            or not path.startswith("/api/v1/")
            or "?" in path
        ):
            raise ValueError("Nonce must bind a canonical mutation route")
        value = secrets.token_urlsafe(32)
        digest = request_digest(method, path, body)
        with self.store.operation_transaction() as db:
            if not is_human_session_context(context, self.store, db=db):
                raise PermissionError(
                    "A current authenticated human session is required"
                )
            db.execute(
                "INSERT INTO governance_human_nonces VALUES(?,?,?,?,0)",
                (_digest(value), context.session_id, digest, int(self.clock()) + 60),
            )
        return {"nonce": value, "request_digest": digest, "expires_in": 60}

    def admit_request(self, context, nonce: str, method: str, path: str, body):
        with self.store.operation_transaction() as db:
            row = db.execute(
                "SELECT * FROM governance_human_nonces WHERE nonce_digest=?",
                (_digest(nonce),),
            ).fetchone()
            if (
                not is_human_session_context(context, self.store, db=db)
                or not row
                or row["consumed"]
                or row["expires_at"] <= int(self.clock())
                or row["session_id"] != context.session_id
                or not hmac.compare_digest(
                    row["request_digest"], request_digest(method, path, body)
                )
            ):
                raise PermissionError(
                    "Human request is expired, replayed or scope-mismatched"
                )
            db.execute(
                "UPDATE governance_human_nonces SET consumed=1 WHERE nonce_digest=?",
                (_digest(nonce),),
            )
            self._audit(
                db,
                "human.request.admitted",
                session_id=context.session_id,
                actor_id=context.subject_id,
                authorization_context_id=context.context_id,
                request_digest=row["request_digest"],
                method=method,
                path=path,
            )

    def logout(self, context):
        with self.store.operation_transaction() as db:
            if not is_human_session_context(context, self.store, db=db):
                raise PermissionError("Human session is not active")
            db.execute(
                "UPDATE governance_human_sessions SET status='REVOKED' WHERE session_id=?",
                (context.session_id,),
            )
            self._audit(
                db,
                "human.session.revoked",
                session_id=context.session_id,
                actor_id=context.subject_id,
            )
        return AuthenticationResponse({"revoked": True}, cookie="")


_configured_auth: HumanSessionAuth | None = None


def get_human_auth():
    """Only trusted host configuration selects an identity provider."""
    global _configured_auth
    if _configured_auth is None:
        import os
        from nous_runtime.governance import get_gate

        root = Path(os.environ.get("NOUS_WORKSPACE_ROOT", ".")).resolve()
        config_path = root / ".nous" / "human-identity.json"
        if not config_path.is_file():
            raise PermissionError(
                "Trusted remote human identity provider is not configured"
            )
        if os.name == "nt":
            raise PermissionError(
                "Remote identity file enrollment requires verified owner access; use the trusted host adapter on Windows"
            )
        if (
            config_path.stat().st_uid != os.getuid()
            or config_path.stat().st_mode & 0o022
        ):
            raise PermissionError(
                "Human identity configuration must be controlled by its owner"
            )
        config = json.loads(config_path.read_text())
        permissions = PermissionEngine(
            tuple(PermissionRule(**item) for item in config.get("permissions", ()))
        )
        _configured_auth = HumanSessionAuth(
            get_gate().store, OIDCHumanIdentityProvider(config), permissions=permissions
        )
    return _configured_auth
