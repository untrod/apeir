"""Safe, read-only source handling for extension inspection."""

from __future__ import annotations

import hashlib
import stat
import tempfile
import zipfile
from contextlib import AbstractContextManager
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
_IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache"}
PACKAGE_MANIFEST_NAMES = {
    "nous.extension.json",
    "pack.yaml",
    "plugin.json",
    "skill.md",
}


class UnsafeExtensionSource(ValueError):
    pass


class ExtensionSource(AbstractContextManager["ExtensionSource"]):
    """Resolve a directory, manifest file, or ZIP without executing content."""

    def __init__(self, source: str | Path):
        self.source = Path(source).expanduser().resolve()
        self.root: Path
        self.preferred_file: Path | None = None
        self._temporary: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> "ExtensionSource":
        try:
            if not self.source.exists():
                raise FileNotFoundError(self.source)
            if self.source.is_dir():
                self.root = self.source
            elif self.source.suffix.lower() == ".zip":
                self._temporary = tempfile.TemporaryDirectory(prefix="nous-extension-")
                extraction_root = Path(self._temporary.name)
                _extract_zip(self.source, extraction_root)
                self.root = _single_package_root(extraction_root)
            elif self.source.is_file():
                if self.source.stat().st_size > MAX_FILE_BYTES:
                    raise UnsafeExtensionSource("manifest exceeds the inspection size limit")
                self.root = self.source.parent
                self.preferred_file = self.source
            else:
                raise UnsafeExtensionSource("extension source must be a regular file or directory")
            _validate_tree(self.root)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


def package_digest(root: Path) -> str:
    """Hash relative paths and contents in a deterministic, portable order."""

    return _digest_files(root, _package_files(root))


def file_digest(path: Path) -> str:
    """Hash one standalone manifest using its filename as the package path."""

    return _digest_files(path.parent, [path])


def is_package_manifest(path: Path | None) -> bool:
    return path is not None and path.name.lower() in PACKAGE_MANIFEST_NAMES


def _digest_files(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        size = path.stat().st_size
        digest.update(size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def package_files(root: Path) -> tuple[Path, ...]:
    return tuple(_package_files(root))


def _package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if any(part in _IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise UnsafeExtensionSource(f"symbolic links are not accepted: {path}")
        if path.is_file():
            if path.stat().st_size > MAX_FILE_BYTES:
                raise UnsafeExtensionSource(f"package file exceeds size limit: {path}")
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _validate_tree(root: Path) -> None:
    total = 0
    files = _package_files(root)
    if len(files) > MAX_ARCHIVE_FILES:
        raise UnsafeExtensionSource("package contains too many files")
    for path in files:
        total += path.stat().st_size
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise UnsafeExtensionSource(f"package path escapes source root: {path}") from exc
    if total > MAX_ARCHIVE_BYTES:
        raise UnsafeExtensionSource("package exceeds the total size limit")


def _extract_zip(source: Path, target: Path) -> None:
    total = 0
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_FILES:
            raise UnsafeExtensionSource("archive contains too many entries")
        for info in infos:
            name = info.filename.replace("\\", "/")
            path = PurePosixPath(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                not name
                or path.is_absolute()
                or ".." in path.parts
                or any(":" in part for part in path.parts)
                or stat.S_ISLNK(mode)
                or info.flag_bits & 0x1
            ):
                raise UnsafeExtensionSource(f"unsafe archive entry: {info.filename}")
            total += info.file_size
            if info.file_size > MAX_FILE_BYTES or total > MAX_ARCHIVE_BYTES:
                raise UnsafeExtensionSource("archive exceeds extraction size limits")
        archive.extractall(target)


def _single_package_root(root: Path) -> Path:
    children = [item for item in root.iterdir() if item.name not in {"__MACOSX"}]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return root
