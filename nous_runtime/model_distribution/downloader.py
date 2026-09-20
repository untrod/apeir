"""Transactional, resumable and checksum-verified model downloader."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.model_distribution.catalog import DownloadArtifact
from nous_runtime.model_distribution.control import (
    DownloadCancelledError,
    DownloadControl,
)
from nous_runtime.model_runtime.errors import ModelResolutionError
from nous_runtime.model_runtime.models import utc_now


ProgressCallback = Callable[[int, int], None]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_url(url: str) -> str:
    """Remove credentials, query tokens, and fragments from diagnostics."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return url
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    authority = hostname
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, authority, parsed.path, "", "")
    )


@dataclass(frozen=True)
class DistributionTransaction:
    transaction_id: str
    operation: str
    target: str
    state: str = "created"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "target": self.target,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "details": dict(self.details),
        }


class TransactionJournal:
    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._transactions: dict[str, DistributionTransaction] = {}
        self._load()

    def begin(
        self,
        operation: str,
        target: str,
        details: Mapping[str, Any] | None = None,
    ) -> DistributionTransaction:
        transaction = DistributionTransaction(
            transaction_id=f"dist_{uuid.uuid4().hex}",
            operation=operation,
            target=target,
            details=dict(details or {}),
        )
        self._transactions[transaction.transaction_id] = transaction
        self._save()
        return transaction

    def update(
        self,
        transaction_id: str,
        state: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> DistributionTransaction:
        current = self._transactions.get(transaction_id)
        if current is None:
            raise ModelResolutionError(
                f"distribution transaction not found: {transaction_id}"
            )
        updated = replace(
            current,
            state=str(state),
            updated_at=utc_now(),
            details={
                **dict(current.details),
                **dict(details or {}),
            },
        )
        self._transactions[transaction_id] = updated
        self._save()
        return updated

    def incomplete(self) -> list[DistributionTransaction]:
        terminal = {"completed", "failed", "cancelled", "rolled_back"}
        return sorted(
            (
                item
                for item in self._transactions.values()
                if item.state not in terminal
            ),
            key=lambda item: item.created_at,
        )

    def _load(self) -> None:
        if not self.storage_path.is_file():
            return
        try:
            data = json.loads(
                self.storage_path.read_text(encoding="utf-8")
            )
            for item in data.get("transactions") or ():
                transaction = DistributionTransaction(
                    transaction_id=str(
                        item.get("transaction_id") or ""
                    ),
                    operation=str(item.get("operation") or ""),
                    target=str(item.get("target") or ""),
                    state=str(item.get("state") or "created"),
                    created_at=str(item.get("created_at") or utc_now()),
                    updated_at=str(item.get("updated_at") or utc_now()),
                    details=dict(item.get("details") or {}),
                )
                self._transactions[
                    transaction.transaction_id
                ] = transaction
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelResolutionError(
                f"failed to load distribution journal: {exc}"
            ) from exc

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(
            self.storage_path.suffix + ".tmp"
        )
        temporary.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "transactions": [
                        item.to_dict()
                        for item in self._transactions.values()
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.storage_path)


class ResumableModelDownloader:
    def __init__(
        self,
        destination_root: str | Path,
        *,
        journal: TransactionJournal | None = None,
        chunk_size: int = 1024 * 1024,
        approved_insecure_http_hosts: Iterable[str] = (),
    ) -> None:
        if chunk_size < 1:
            raise ModelResolutionError(
                "download chunk_size must be positive"
            )
        self.destination_root = Path(destination_root)
        self.journal = journal
        self.chunk_size = chunk_size
        self.approved_insecure_http_hosts = frozenset(
            str(host).strip().casefold()
            for host in approved_insecure_http_hosts
            if str(host).strip()
        )

    def download(
        self,
        artifact: DownloadArtifact,
        *,
        progress: ProgressCallback | None = None,
        control: DownloadControl | None = None,
    ) -> Path:
        destination = self.destination_root / artifact.filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (
            destination.is_file()
            and sha256_file(destination) == artifact.sha256
        ):
            return destination
        partial = destination.with_suffix(destination.suffix + ".part")
        transaction = (
            self.journal.begin(
                "download",
                str(destination),
                {"artifact_id": artifact.artifact_id},
            )
            if self.journal
            else None
        )
        errors = []
        try:
            for url in artifact.urls:
                safe_url = "<invalid-url>"
                try:
                    safe_url = _safe_url(url)
                    if control:
                        control.checkpoint()
                    if transaction:
                        self.journal.update(
                            transaction.transaction_id,
                            "downloading",
                            details={"url": safe_url},
                        )
                    self._ensure_capacity(partial, artifact.size_bytes)
                    self._transfer(
                        url,
                        partial,
                        artifact.size_bytes,
                        progress,
                        control,
                    )
                    if (
                        artifact.size_bytes
                        and partial.stat().st_size
                        != artifact.size_bytes
                    ):
                        raise ModelResolutionError(
                            "download size mismatch: "
                            f"expected {artifact.size_bytes}, "
                            f"got {partial.stat().st_size}"
                        )
                    actual = sha256_file(partial)
                    if actual != artifact.sha256:
                        raise ModelResolutionError(
                            "download checksum mismatch: "
                            f"expected {artifact.sha256}, got {actual}"
                        )
                    os.replace(partial, destination)
                    if transaction:
                        self.journal.update(
                            transaction.transaction_id,
                            "completed",
                            details={"sha256": actual},
                        )
                    return destination
                except DownloadCancelledError:
                    raise
                except Exception as exc:
                    errors.append(f"{safe_url}: {exc}")
        except DownloadCancelledError:
            if transaction:
                self.journal.update(
                    transaction.transaction_id,
                    "cancelled",
                )
            raise
        if transaction:
            self.journal.update(
                transaction.transaction_id,
                "failed",
                details={"errors": errors},
            )
        raise ModelResolutionError(
            "all download mirrors failed: " + "; ".join(errors)
        )

    def _ensure_capacity(self, partial: Path, expected_size: int) -> None:
        if expected_size <= 0:
            return
        existing = partial.stat().st_size if partial.is_file() else 0
        remaining = max(expected_size - existing, 0)
        available = shutil.disk_usage(self.destination_root).free
        if available < remaining:
            raise ModelResolutionError(
                "insufficient disk space for model download: "
                f"need {remaining} bytes, have {available}"
            )

    def _transfer(
        self,
        url: str,
        partial: Path,
        expected_size: int,
        progress: ProgressCallback | None,
        control: DownloadControl | None,
    ) -> None:
        parsed = urllib.parse.urlparse(url)
        local_path = Path(url)
        if local_path.is_absolute() or parsed.scheme in {"", "file"}:
            source = Path(
                urllib.request.url2pathname(parsed.path)
                if parsed.scheme == "file"
                else url
            )
            if not source.is_file():
                raise ModelResolutionError(
                    f"download source does not exist: {source}"
                )
            downloaded = 0
            with source.open("rb") as source_stream:
                with partial.open("wb") as output:
                    while True:
                        if control:
                            control.checkpoint()
                        chunk = source_stream.read(self.chunk_size)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, expected_size)
            return

        self._validate_remote_url(parsed)
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        request = urllib.request.Request(url, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.URLError as exc:
            raise ModelResolutionError(
                f"download connection failed: {exc}"
            ) from exc
        with response:
            status = getattr(response, "status", 200)
            append = bool(offset and status == 206)
            if offset and not append:
                offset = 0
            mode = "ab" if append else "wb"
            with partial.open(mode) as output:
                downloaded = offset
                while True:
                    if control:
                        control.checkpoint()
                    chunk = response.read(self.chunk_size)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, expected_size)

    def _validate_remote_url(
        self,
        parsed: urllib.parse.ParseResult,
    ) -> None:
        scheme = parsed.scheme.casefold()
        if scheme == "https":
            return
        host = (parsed.hostname or "").casefold()
        if (
            scheme == "http"
            and host
            and host in self.approved_insecure_http_hosts
        ):
            return
        if scheme == "http":
            raise ModelResolutionError(
                "plain HTTP model downloads are disabled; explicitly "
                "approve the trusted LAN host to continue"
            )
        raise ModelResolutionError(
            f"unsupported model download URL scheme: {scheme or '<empty>'}"
        )


__all__ = [
    "DistributionTransaction",
    "ProgressCallback",
    "ResumableModelDownloader",
    "TransactionJournal",
    "sha256_file",
]
