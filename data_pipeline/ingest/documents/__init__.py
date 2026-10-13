"""PDF extraction and document import entry points."""

import io

from pypdf import PdfReader

from data_pipeline.documents.base import DocumentError


def extract(raw):
    if not raw.startswith(b"%PDF-"):
        raise DocumentError("invalid_pdf")
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise DocumentError("encrypted_pdf_unsupported")
        pages = [p.extract_text(extraction_mode="layout") for p in reader.pages]
    except DocumentError:
        raise
    except Exception:
        raise DocumentError("pdf_extraction_failed") from None
    if not pages or any(not p.strip() for p in pages):
        raise DocumentError("image_only_or_empty_page")
    return pages
