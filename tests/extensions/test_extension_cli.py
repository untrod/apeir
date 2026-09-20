from __future__ import annotations

from nous_runtime.extensions.cli import _emit


def test_human_output_supports_kernel_decisions(capsys):
    _emit(
        {
            "admitted": True,
            "extension_id": "openapi:native-integration",
            "granted_capabilities": ["network.connect"],
            "receipt_id": "authorization-1",
        },
        False,
    )

    output = capsys.readouterr().out
    assert "Extension: openapi:native-integration" in output
    assert "Authority: kernel_grant" in output
    assert "Granted: network.connect" in output
    assert "Receipt: authorization-1" in output
