"""Parsers (M2): file → extracted text. Originals stay sacred in the
content-addressed store; only the derived text lands in TerminusDB.

Dispatch by extension (magic-byte sniffing for the common cases):
  .pdf .docx .xlsx .xls .csv .json .txt .md .eml .msg .mbox .html
Images (.png .jpg .jpeg .gif .tiff .webp) have no local parser — they go to
the OCR path on the BYO-key LLM (`ocr=True` in ingest), never guessed.
Unknown → quarantined (listed, never dropped).

Deps are boring and standard: pypdf, python-docx, openpyxl, extract-msg.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import json
import mailbox
import zipfile
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".markdown", ".log", ".csv", ".json", ".html", ".htm", ".xml", ".yaml", ".yml"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".tiff", ".tif", ".webp", ".bmp"}
KNOWN = TEXT_EXTS | {".pdf", ".docx", ".xlsx", ".xls", ".eml", ".msg", ".mbox"} | IMAGE_EXTS


class UnknownFormat(Exception):
    pass


class NeedsOCR(Exception):
    pass


def media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".eml": "message/rfc822", ".msg": "application/vnd.ms-outlook",
        ".mbox": "application/mbox",
        ".json": "application/json", ".csv": "text/csv",
    }.get(ext, "text/plain" if ext in TEXT_EXTS else
           ("image/" + ext[1:] if ext in IMAGE_EXTS else "application/octet-stream"))


def parse(path: Path) -> str:
    """Extract text from a file. Raises UnknownFormat / NeedsOCR."""
    ext = path.suffix.lower()
    data = path.read_bytes()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    if ext in (".xlsx", ".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            out.append(f"--- sheet: {ws.title} ---")
            for row in ws.iter_rows(values_only=True):
                out.append("\t".join("" if c is None else str(c) for c in row))
        return "\n".join(out)
    if ext == ".csv":
        return data.decode("utf-8", errors="replace")
    if ext == ".json":
        return json.dumps(json.loads(data.decode("utf-8", errors="replace")), indent=2)
    if ext in (".txt", ".md", ".markdown", ".log", ".html", ".htm", ".xml", ".yaml", ".yml"):
        return data.decode("utf-8", errors="replace")
    if ext == ".eml":
        msg = email.message_from_bytes(data, policy=email.policy.default)
        parts = [f"From: {msg.get('From')}", f"To: {msg.get('To')}", f"Subject: {msg.get('Subject')}",
                 f"Date: {msg.get('Date')}", ""]
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                parts.append(part.get_content())
        return "\n".join(parts)
    if ext == ".msg":
        import extract_msg
        m = extract_msg.openMsg(str(path))
        try:
            body = m.body or ""
            return f"From: {m.sender}\nTo: {m.to}\nSubject: {m.subject}\nDate: {m.date}\n\n{body}"
        finally:
            m.close()
    if ext == ".mbox":
        mb = mailbox.mbox(str(path))
        return "\n\n---\n\n".join(
            f"From: {m.get('From')}\nSubject: {m.get('Subject')}\nDate: {m.get('Date')}\n\n"
            + (m.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
            for m in mb)
    if ext in IMAGE_EXTS:
        raise NeedsOCR(ext)
    raise UnknownFormat(ext or "(no extension)")


def parser_name(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "ocr"
    if ext in (".txt", ".md", ".markdown", ".log", ".html", ".htm", ".xml", ".yaml", ".yml"):
        return "text"
    return ext.lstrip(".") or "text"
