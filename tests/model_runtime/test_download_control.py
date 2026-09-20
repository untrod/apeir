from __future__ import annotations

import hashlib
import json
import threading
import urllib.error

import pytest

from nous_runtime.model_distribution import (
    DownloadArtifact,
    DownloadCancelledError,
    DownloadControl,
    ResumableModelDownloader,
    TransactionJournal,
)
from nous_runtime.model_runtime import ModelResolutionError


def _artifact(url: str, payload: bytes = b"model") -> DownloadArtifact:
    return DownloadArtifact(
        artifact_id="controlled-model",
        urls=(url,),
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        filename="controlled.gguf",
    )


def test_download_control_pauses_resumes_and_cancels() -> None:
    control = DownloadControl()
    released = threading.Event()

    control.pause()
    worker = threading.Thread(
        target=lambda: (control.checkpoint(), released.set()),
        daemon=True,
    )
    worker.start()
    assert not released.wait(timeout=0.05)

    control.resume()
    assert released.wait(timeout=1)

    control.cancel()
    with pytest.raises(DownloadCancelledError, match="cancelled"):
        control.checkpoint()


def test_cancelled_download_closes_transaction(tmp_path) -> None:
    source = tmp_path / "source.gguf"
    source.write_bytes(b"model")
    journal_path = tmp_path / "journal.json"
    journal = TransactionJournal(journal_path)
    downloader = ResumableModelDownloader(
        tmp_path / "downloads",
        journal=journal,
    )
    control = DownloadControl()
    control.cancel()

    with pytest.raises(DownloadCancelledError):
        downloader.download(_artifact(str(source)), control=control)

    assert journal.incomplete() == []
    transactions = json.loads(
        journal_path.read_text(encoding="utf-8")
    )["transactions"]
    assert transactions[0]["state"] == "cancelled"


def test_plain_http_requires_explicit_host_approval(tmp_path) -> None:
    downloader = ResumableModelDownloader(tmp_path / "downloads")

    with pytest.raises(ModelResolutionError, match="plain HTTP"):
        downloader.download(
            _artifact("http://127.0.0.1/model.gguf")
        )


def test_download_diagnostics_redact_query_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    def offline(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    downloader = ResumableModelDownloader(tmp_path / "downloads")

    with pytest.raises(ModelResolutionError) as captured:
        downloader.download(
            _artifact(
                "https://models.example/model.gguf?token=super-secret"
            )
        )

    message = str(captured.value)
    assert "super-secret" not in message
    assert "https://models.example/model.gguf" in message
