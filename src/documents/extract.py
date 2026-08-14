"""Text extraction from fetched attachments. Never executes document content.

pypdf is pure-Python and parses structure only. Extraction is bounded (page cap
and character cap) so a hostile or enormous file cannot exhaust the worker.
"""
import io

from ..log import log

MAX_PAGES = 400
MAX_CHARS = 1_200_000     # ~600 pages of dense text


def extract_text(content: bytes, filename: str = "") -> dict:
    """Returns {text, page_count, pages: [(page_no, text)], status}."""
    if not content:
        return {"status": "failed", "text": "", "page_count": 0, "pages": []}
    if filename.lower().endswith(".txt"):
        text = content.decode("utf-8", errors="replace")[:MAX_CHARS]
        return {"status": "extracted", "text": text, "page_count": 1,
                "pages": [(1, text)], "method": "text"}
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content), strict=False)
        pages, total = [], 0
        for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 — one bad page must not kill the doc
                page_text = ""
            if page_text:
                pages.append((index, page_text))
                total += len(page_text)
            if total > MAX_CHARS:
                break
        text = "\n".join(t for _, t in pages)[:MAX_CHARS]
        if not text.strip():
            # Scanned/image PDF: try bounded OCR; honest status either way.
            from .ocr import ocr_available, ocr_pdf
            if ocr_available():
                ocr = ocr_pdf(content, total_pages=len(reader.pages))
                if ocr["status"] == "extracted":
                    return {"status": "extracted", "text": ocr["text"],
                            "pages": ocr["pages"],
                            "page_count": len(reader.pages),
                            "method": "ocr", "ocr_pages": ocr["ocr_pages"],
                            "note": ocr["note"]}
                return {"status": ocr["status"], "text": "", "pages": [],
                        "page_count": len(reader.pages), "note": ocr["note"]}
            return {"status": "unsupported", "text": "", "pages": [],
                    "page_count": len(reader.pages),
                    "note": "no embedded text (likely a scanned image; OCR not enabled)"}
        return {"status": "extracted", "text": text, "pages": pages,
                "page_count": len(reader.pages), "method": "pypdf"}
    except Exception as exc:  # noqa: BLE001 — malformed PDFs are expected input
        log("document_extract_error", error=type(exc).__name__)
        return {"status": "failed", "text": "", "page_count": 0, "pages": [],
                "note": type(exc).__name__}
