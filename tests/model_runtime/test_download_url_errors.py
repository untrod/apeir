from __future__ import annotations

import hashlib

import pytest

from nous_runtime.model_distribution import (
    DownloadArtifact,
    ResumableModelDownloader,
)
from nous_runtime.model_runtime import ModelResolutionError


def test_malformed_download_url_uses_unified_redacted_error(
    tmp_path,
) -> None:
    artifact = DownloadArtifact(
        artifact_id="malformed-url",
        urls=(
            "https://models.example:invalid/model.gguf?token=secret",
        ),
        sha256=hashlib.sha256(b"x").hexdigest(),
        size_bytes=1,
        filename="model.gguf",
    )

    with pytest.raises(ModelResolutionError) as captured:
        ResumableModelDownloader(tmp_path).download(artifact)

    assert "secret" not in str(captured.value)
    assert "<invalid-url>" in str(captured.value)
