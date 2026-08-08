"""PDF decryption and text/table extraction helpers.

Everything here is pure-Python (pypdf + pdfplumber) so the app needs no
system-level poppler/qpdf binaries — it works the same in Docker, on Fly, and
on a bare laptop.
"""
from __future__ import annotations

import io
from contextlib import contextmanager
from typing import Iterator, Optional

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


class WrongPasswordError(Exception):
    """Raised when a PDF is encrypted and the supplied password doesn't open it."""


class PasswordRequiredError(Exception):
    """Raised when a PDF is encrypted and no password was supplied."""


class PdfParseError(Exception):
    """Generic unrecoverable PDF read failure."""


def is_encrypted(file_bytes: bytes) -> bool:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return reader.is_encrypted
    except PdfReadError as exc:
        raise PdfParseError(f"Could not read this file as a PDF: {exc}") from exc


def decrypt_pdf_bytes(file_bytes: bytes, password: Optional[str] = None) -> bytes:
    """Return a decrypted copy of the PDF as bytes.

    If the PDF isn't encrypted, returns the original bytes unchanged. If it
    is encrypted and no/incorrect password is given, raises a clear error
    the UI can show back to the user.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except PdfReadError as exc:
        raise PdfParseError(f"Could not read this file as a PDF: {exc}") from exc

    if not reader.is_encrypted:
        return file_bytes

    if not password:
        raise PasswordRequiredError("This PDF is password-protected — enter its password to continue.")

    result = reader.decrypt(password)
    if result == 0:
        raise WrongPasswordError("That password didn't unlock this PDF. Double-check it and try again.")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@contextmanager
def open_pdf(file_bytes: bytes, password: Optional[str] = None) -> Iterator[pdfplumber.PDF]:
    """Decrypt (if needed) and yield an open pdfplumber.PDF for extraction."""
    decrypted = decrypt_pdf_bytes(file_bytes, password)
    pdf = pdfplumber.open(io.BytesIO(decrypted))
    try:
        yield pdf
    finally:
        pdf.close()


def full_text(pdf: pdfplumber.PDF) -> str:
    """Concatenate all pages' text.

    pdfplumber's default word-spacing tolerance (x_tolerance=3) is too
    coarse for the condensed fonts several bank statement generators use —
    it silently merges adjacent words ("AccountBranch", "PageNo.:1") with no
    space between them, which then breaks every downstream regex. A tight
    x_tolerance fixes that; it's the single most important knob here, more
    than layout=True (which we don't need — the line engine reconciles
    against the running balance rather than relying on column position).
    """
    parts = []
    for page in pdf.pages:
        try:
            parts.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
        except Exception:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def all_tables(pdf: pdfplumber.PDF) -> list[list[list[Optional[str]]]]:
    """Every table pdfplumber can find, across every page, in order."""
    tables = []
    for page in pdf.pages:
        for tbl in page.extract_tables():
            if tbl:
                tables.append(tbl)
    return tables
