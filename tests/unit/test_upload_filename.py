"""Upload filename resolution for multipart / UC staging."""

from __future__ import annotations

from app.services.upload_filename import resolve_upload_filename


def test_prefers_client_hint_over_generic_multipart_name():
    name = resolve_upload_filename(
        upload_name="blob",
        client_hint="quarterly-report.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.4",
    )
    assert name == "quarterly-report.pdf"


def test_uses_multipart_when_usable():
    name = resolve_upload_filename(
        upload_name="memo.md",
        client_hint=None,
        content_type="text/markdown",
        content=b"# Title",
    )
    assert name == "memo.md"


def test_sniffs_pdf_when_names_missing():
    name = resolve_upload_filename(
        upload_name=None,
        client_hint=None,
        content_type="application/octet-stream",
        content=b"%PDF-1.4 fake",
    )
    assert name == "upload.pdf"
