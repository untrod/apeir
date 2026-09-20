"""Tests for Control Plane authentication."""

import pytest


@pytest.fixture(autouse=True)
def isolated_session_token(monkeypatch, tmp_path):
    monkeypatch.setenv("NOUS_SESSION_TOKEN_FILE", str(tmp_path / "session.token"))


class TestControlPlaneAuth:
    """Test session token generation, verification, and security properties."""

    def test_token_generation(self):
        """Token should be 256-bit (64 hex chars) random."""
        from nous_runtime.control_plane.auth import ControlPlaneAuth
        auth = ControlPlaneAuth()
        token = auth.generate()
        assert len(token) == 64  # 32 bytes = 64 hex chars
        assert token != auth.generate()  # each call is unique
        auth.revoke()

    def test_token_verification_constant_time(self):
        """Token verification uses constant-time comparison."""
        from nous_runtime.control_plane.auth import ControlPlaneAuth
        auth = ControlPlaneAuth()
        token = auth.generate()
        assert auth.verify(token) is True
        assert auth.verify("wrong_token") is False
        assert auth.verify(token + "a") is False
        auth.revoke()

    def test_token_revocation(self):
        """Revoked token should not verify."""
        from nous_runtime.control_plane.auth import ControlPlaneAuth
        auth = ControlPlaneAuth()
        token = auth.generate()
        auth.revoke()
        assert auth.verify(token) is False
        assert auth.token is None

    def test_token_env_var_set(self):
        """Token should be set as NOUS_API_TOKEN env var."""
        import os
        from nous_runtime.control_plane.auth import ControlPlaneAuth
        auth = ControlPlaneAuth()
        token = auth.generate()
        assert os.environ.get("NOUS_API_TOKEN") == token
        auth.revoke()
        assert "NOUS_API_TOKEN" not in os.environ

    def test_token_file_created(self):
        """Token should be written with verified owner-only permissions."""
        import os
        import stat
        import subprocess

        from nous_runtime.control_plane.auth import ControlPlaneAuth
        from nous_runtime.control_plane.auth import _windows_acl_identity

        auth = ControlPlaneAuth()
        token = auth.generate()
        assert auth.token_file is not None
        assert os.path.exists(auth.token_file)
        with open(auth.token_file, "r") as token_file:
            assert token_file.read().strip() == token
        if os.name == "nt":
            completed = subprocess.run(
                ["icacls.exe", auth.token_file],
                capture_output=True,
                encoding="mbcs",
                errors="replace",
                timeout=5,
                check=False,
            )
            assert completed.returncode == 0
            assert "(I)" not in completed.stdout
            assert (
                _windows_acl_identity().casefold()
                in completed.stdout.casefold()
            )
        else:
            mode = stat.S_IMODE(os.stat(auth.token_file).st_mode)
            assert mode == stat.S_IRUSR | stat.S_IWUSR
        auth.revoke()
        assert not os.path.exists(auth.token_file)

    def test_permission_hardening_failure_is_fail_closed(
        self,
        monkeypatch,
        tmp_path,
    ):
        """An unverifiable token file must never leave an active session."""
        import os
        import nous_runtime.control_plane.auth as auth_module

        token_path = tmp_path / "session.token"
        monkeypatch.setenv("NOUS_SESSION_TOKEN_FILE", str(token_path))

        def reject_permissions(_path):
            raise PermissionError("ACL unavailable")

        monkeypatch.setattr(
            auth_module,
            "_restrict_token_permissions",
            reject_permissions,
        )
        auth = auth_module.ControlPlaneAuth()

        with pytest.raises(PermissionError, match="ACL unavailable"):
            auth.generate()

        assert auth.token is None
        assert "NOUS_API_TOKEN" not in os.environ
        assert not token_path.exists()

class TestCORS:
    """Test CORS configuration."""

    def test_allowed_origins(self):
        from nous_runtime.control_plane.auth import CORS_ALLOWED_ORIGINS
        assert "tauri://localhost" in CORS_ALLOWED_ORIGINS
        assert "https://tauri.localhost" in CORS_ALLOWED_ORIGINS
        assert any("127.0.0.1" in o for o in CORS_ALLOWED_ORIGINS)

    def test_cors_headers_applied(self):
        from nous_runtime.control_plane.auth import add_cors_headers
        headers = {}
        add_cors_headers(headers, "tauri://localhost")
        assert "Access-Control-Allow-Origin" in headers
        assert headers["Access-Control-Allow-Origin"] == "tauri://localhost"
        assert "Access-Control-Allow-Credentials" in headers

    def test_disallowed_origin_no_headers(self):
        from nous_runtime.control_plane.auth import add_cors_headers
        headers = {}
        add_cors_headers(headers, "https://evil.com")
        assert "Access-Control-Allow-Origin" not in headers
