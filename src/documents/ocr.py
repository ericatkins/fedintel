"""OCR fallback for scanned PDFs. Bounded, sandboxed, honestly labeled.

Requires the system binaries `pdftoppm` (poppler) and `tesseract`; when they
are absent — or FEDINTEL_OCR=0 — the pipeline behaves exactly as before and
scanned documents keep the honest `unsupported` status.

Resource discipline (a hostile or enormous scan must not take the worker down):
- at most OCR_MAX_PAGES pages are rasterized, at OCR_DPI;
- every subprocess runs with an absolute binary path, no shell, a private
  temp directory, closed stdin, and a hard timeout;
- a total wall-clock budget caps the whole document.

Truthfulness: OCR output is machine-read text from images. The extraction is
labeled method='ocr' with the page coverage stated, and every requirement
mined from OCR text has its confidence capped (OCR_CONFIDENCE_CAP) and its
method tagged so the UI's evidence drawers show the reduced reliability.
"""
import os
import shutil

# OCR requires external binaries; every call is sandboxed in _run().
import subprocess  # nosec B404
import tempfile
import time

from ..log import log

OCR_MAX_PAGES = 20
OCR_DPI = 150
OCR_PAGE_TIMEOUT = 30          # seconds per tesseract invocation
OCR_TOTAL_BUDGET = 240         # seconds per document, wall clock
OCR_CONFIDENCE_CAP = 55        # requirements mined from OCR text cap here
MAX_CHARS = 1_200_000


def cap_requirements(requirements: list[dict]) -> list[dict]:
    """Requirements mined from OCR text: confidence capped, method tagged."""
    return [
        {**r, "confidence": min(r.get("confidence", 70), OCR_CONFIDENCE_CAP),
         "method": f"{r.get('method', 'rule')}+ocr"}
        for r in requirements]


def ocr_available() -> bool:
    if os.getenv("FEDINTEL_OCR", "1") == "0":
        return False
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def _run(argv: list[str], cwd: str, timeout: int) -> subprocess.CompletedProcess:
    # Justification (B603/S603): argv[0] is an absolute path from
    # shutil.which, args are fixed strings + paths inside our private
    # tempdir, shell=False, stdin closed, hard timeout. Document bytes are
    # written to disk and never interpolated into the command line.
    return subprocess.run(  # noqa: S603  # nosec B603
        argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
        timeout=timeout, check=False)


def ocr_pdf(content: bytes, total_pages: int | None = None) -> dict:
    """OCR the first OCR_MAX_PAGES pages of a PDF given as bytes.

    Returns {status, text, pages: [(page_no, text)], ocr_pages, note}."""
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not (pdftoppm and tesseract):
        return {"status": "unsupported", "text": "", "pages": [],
                "ocr_pages": 0, "note": "OCR binaries not installed"}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fedintel-ocr-") as tmp:
        pdf_path = os.path.join(tmp, "doc.pdf")
        with open(pdf_path, "wb") as f:
            f.write(content)
        try:
            proc = _run([pdftoppm, "-png", "-r", str(OCR_DPI),
                         "-f", "1", "-l", str(OCR_MAX_PAGES),
                         pdf_path, os.path.join(tmp, "page")],
                        cwd=tmp, timeout=OCR_TOTAL_BUDGET // 2)
        except subprocess.TimeoutExpired:
            log("ocr_raster_timeout")
            return {"status": "failed", "text": "", "pages": [],
                    "ocr_pages": 0, "note": "OCR rasterization timed out"}
        if proc.returncode != 0:
            log("ocr_raster_failed", code=proc.returncode)
            return {"status": "failed", "text": "", "pages": [],
                    "ocr_pages": 0, "note": "PDF rasterization failed"}
        images = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
        pages, total_chars = [], 0
        for image in images:
            if time.monotonic() - started > OCR_TOTAL_BUDGET:
                log("ocr_budget_exhausted", pages_done=len(pages))
                break
            # pdftoppm names files page-1.png … page-N.png
            page_no_text = image.rsplit("-", 1)[-1].split(".")[0]
            page_no = int(page_no_text) if page_no_text.isdigit() else \
                len(pages) + 1
            try:
                proc = _run([tesseract, os.path.join(tmp, image), "stdout",
                             "--dpi", str(OCR_DPI)],
                            cwd=tmp, timeout=OCR_PAGE_TIMEOUT)
            except subprocess.TimeoutExpired:
                log("ocr_page_timeout", page=page_no)
                continue
            if proc.returncode != 0:
                continue
            page_text = proc.stdout.decode("utf-8", errors="replace").strip()
            if page_text:
                pages.append((page_no, page_text))
                total_chars += len(page_text)
            if total_chars > MAX_CHARS:
                break
        text = "\n".join(t for _, t in pages)[:MAX_CHARS]
        if not text.strip():
            return {"status": "unsupported", "text": "", "pages": [],
                    "ocr_pages": 0,
                    "note": "OCR produced no readable text"}
        covered = len(pages)
        total = total_pages or covered
        note = (f"OCR of scanned document — {covered} of {total} page(s) "
                "machine-read; text reliability is reduced")
        return {"status": "extracted", "text": text, "pages": pages,
                "ocr_pages": covered, "note": note}
