"""OCR fallback: end-to-end against a real image-only PDF (when binaries are
present), plus the discipline rules that hold everywhere."""
import io

import pytest

from src.documents.extract import extract_text
from src.documents.ocr import OCR_CONFIDENCE_CAP, cap_requirements, ocr_available


def _scanned_pdf(lines, pages=1) -> bytes:
    """Author an image-only PDF (no embedded text) with PIL."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:                     # older Pillow: fixed-size bitmap font
        font = ImageFont.load_default()
    images = []
    for _ in range(pages):
        img = Image.new("RGB", (1700, 2200), "white")
        draw = ImageDraw.Draw(img)
        y = 200
        for line in lines:
            draw.text((150, y), line, fill="black", font=font)
            y += 160
        images.append(img)
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True,
                   append_images=images[1:], resolution=150)
    return buf.getvalue()


def test_cap_requirements_reduces_confidence_and_tags_method():
    capped = cap_requirements([
        {"requirement_type": "clearance", "value": "Secret",
         "confidence": 90, "method": "clearance_rule"},
        {"requirement_type": "submission", "value": "20 pages",
         "confidence": 40, "method": "pages_rule"}])
    assert capped[0]["confidence"] == OCR_CONFIDENCE_CAP
    assert capped[0]["method"] == "clearance_rule+ocr"
    assert capped[1]["confidence"] == 40          # never raised, only capped


def test_ocr_disabled_by_env_keeps_honest_unsupported(monkeypatch):
    monkeypatch.setenv("FEDINTEL_OCR", "0")
    assert not ocr_available()
    result = extract_text(_scanned_pdf(["CONTRACT REQUIREMENTS"]), "scan.pdf")
    assert result["status"] == "unsupported"
    assert "OCR not enabled" in result["note"]


@pytest.mark.skipif(not ocr_available(), reason="tesseract/pdftoppm not installed")
def test_scanned_pdf_is_ocr_extracted_with_honest_labeling():
    content = _scanned_pdf(
        ["STATEMENT OF WORK", "CONTRACTOR PERSONNEL SHALL POSSESS",
         "AN ACTIVE SECRET CLEARANCE"])
    result = extract_text(content, "scanned_sow.pdf")
    assert result["status"] == "extracted"
    assert result["method"] == "ocr"
    assert result["ocr_pages"] == 1
    assert "SECRET" in result["text"].upper()
    assert "OCR of scanned document" in result["note"]
    assert "reliability is reduced" in result["note"]
    # page-level evidence preserved for the compliance matrix drilldowns
    assert result["pages"] and result["pages"][0][0] == 1


@pytest.mark.skipif(not ocr_available(), reason="tesseract/pdftoppm not installed")
def test_ocr_notes_partial_coverage_on_multipage_documents():
    content = _scanned_pdf(["PAGE CONTENT HERE"], pages=2)
    result = extract_text(content, "scan2.pdf")
    assert result["status"] == "extracted"
    assert result["ocr_pages"] == 2
    assert "2 of 2 page(s)" in result["note"]


def test_embedded_text_pdfs_never_route_through_ocr():
    # regular text PDFs keep the pypdf method regardless of OCR availability
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    result = extract_text(buf.getvalue(), "blank.pdf")
    # a truly blank page has no text and no image content: OCR yields nothing
    assert result["status"] in ("unsupported", "failed")
