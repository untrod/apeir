"""Fail-closed structural verification for generated DOCX and PDF artifacts."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from nous_runtime.documents.models import DocumentIR

_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_ZIP_ENTRIES = 2_000
_MAX_ZIP_UNCOMPRESSED = 100 * 1024 * 1024
_FORBIDDEN_DOCX_NAMES = ("vbaproject", "activex", "embeddings/", "oleobject")
_FORBIDDEN_PDF_TOKENS = (b"/JavaScript", b"/JS ", b"/Launch", b"/EmbeddedFile", b"/OpenAction")


class DocumentVerificationError(ValueError):
    """Generated artifact did not meet the safe document contract."""


def _base(path: Path, document: DocumentIR, kind: str) -> dict:
    data = path.read_bytes()
    return {
        "ok": True,
        "format": kind,
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "document_id": document.document_id,
        "ir_sha256": document.digest(),
        "checks": [],
    }


def verify_docx(path: Path, document: DocumentIR) -> dict:
    if not path.is_file() or path.suffix.lower() != ".docx":
        raise DocumentVerificationError("DOCX artifact is missing or has the wrong extension")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise DocumentVerificationError("DOCX artifact exceeds 50 MiB")
    report = _base(path, document, "docx")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ZIP_ENTRIES:
                raise DocumentVerificationError("DOCX contains too many ZIP entries")
            total = sum(item.file_size for item in entries)
            if total > _MAX_ZIP_UNCOMPRESSED:
                raise DocumentVerificationError("DOCX uncompressed content exceeds 100 MiB")
            names = [item.filename.replace("\\", "/") for item in entries]
            for name in names:
                lowered = name.lower()
                if name.startswith("/") or ".." in Path(name).parts:
                    raise DocumentVerificationError("DOCX contains an unsafe ZIP path")
                if any(token in lowered for token in _FORBIDDEN_DOCX_NAMES):
                    raise DocumentVerificationError(f"DOCX contains forbidden active content: {name}")
            required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml"}
            if not required.issubset(names):
                raise DocumentVerificationError("DOCX is missing required OOXML parts")
            for name in names:
                if not name.endswith(".rels"):
                    continue
                root = ElementTree.fromstring(archive.read(name))
                for relationship in root:
                    if str(relationship.attrib.get("TargetMode") or "").lower() == "external":
                        raise DocumentVerificationError(f"DOCX contains an external relationship: {name}")
            document_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
            normalized = re.sub(r"<[^>]+>", "", document_xml)
            if document.title not in normalized:
                raise DocumentVerificationError("DOCX does not contain the IR title")
    except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DocumentVerificationError(f"DOCX package is invalid: {exc}") from exc
    report["checks"] = ["zip_paths", "zip_bounds", "required_parts", "no_macros_or_embeds", "no_external_relationships", "title_present"]
    return report


def verify_pdf(path: Path, document: DocumentIR) -> dict:
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise DocumentVerificationError("PDF artifact is missing or has the wrong extension")
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise DocumentVerificationError("PDF artifact exceeds 50 MiB")
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-4096:]:
        raise DocumentVerificationError("PDF header or EOF marker is invalid")
    for token in _FORBIDDEN_PDF_TOKENS:
        if token in data:
            raise DocumentVerificationError(f"PDF contains forbidden active content: {token.decode('ascii').strip()}")
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise DocumentVerificationError("encrypted PDF output is not allowed")
        if not reader.pages or len(reader.pages) > 500:
            raise DocumentVerificationError("PDF page count is outside the 1-500 limit")
        extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
        normalized_text = re.sub(r"\s+", " ", extracted).strip()
        normalized_title = re.sub(r"\s+", " ", document.title).strip()
        if normalized_title not in normalized_text:
            raise DocumentVerificationError("PDF does not contain the IR title")
        page_count = len(reader.pages)
    except DocumentVerificationError:
        raise
    except Exception as exc:
        raise DocumentVerificationError(f"PDF structure is invalid: {exc}") from exc
    report = _base(path, document, "pdf")
    report["page_count"] = page_count
    report["checks"] = ["header_and_eof", "parser_reopen", "not_encrypted", "bounded_pages", "no_javascript_launch_or_embeds", "title_present"]
    return report


__all__ = ["DocumentVerificationError", "verify_docx", "verify_pdf"]