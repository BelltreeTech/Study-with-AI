"""Page-aware PDF extraction; only image pages with insufficient text use OCR."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz


@dataclass(frozen=True)
class ExtractionSettings:
    ocr_text_threshold: int = 20
    ocr_enabled: bool = True
    ocr_language: str = "jpn+eng"
    ocr_dpi: int = 150
    ocr_timeout_seconds: int = 30
    max_pages: int = 1000
    max_ocr_pixels: int = 20_000_000
    max_pdf_bytes: int = 100 * 1024 * 1024
    version: int = 2


class PDFExtractionError(ValueError):
    pass


def _ocr_page(page: fitz.Page, settings: ExtractionSettings) -> str:
    # PyMuPDF renders only the selected page; Poppler is not required.
    import pytesseract
    from PIL import Image
    scale = settings.ocr_dpi / 72
    if page.rect.width * page.rect.height * scale * scale > settings.max_ocr_pixels:
        raise PDFExtractionError("OCR画像サイズが上限を超えています")
    pix = page.get_pixmap(dpi=settings.ocr_dpi, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return str(pytesseract.image_to_string(image, lang=settings.ocr_language,
                                         timeout=settings.ocr_timeout_seconds)).strip()


def extract_text_from_pdf(pdf_path: str | Path | bytes, *,
                          settings: ExtractionSettings | None = None,
                          ocr: Callable | None = None) -> list[dict]:
    settings = settings or ExtractionSettings()
    raw = pdf_path if isinstance(pdf_path, bytes) else Path(pdf_path).read_bytes()
    if len(raw) > settings.max_pdf_bytes:
        raise PDFExtractionError("PDFが読込サイズ上限を超えています")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise PDFExtractionError("PDFを開けません。破損または未対応の形式です") from exc
    pages = []
    with doc:
        if doc.is_encrypted:
            raise PDFExtractionError("暗号化PDFは未対応です")
        if len(doc) > settings.max_pages:
            raise PDFExtractionError("PDFのページ数が上限を超えています")
        for page_number, page in enumerate(doc, start=1):
            warnings: list[str] = []
            try:
                text = page.get_text("text").strip()
                image_page = bool(page.get_images())
            except Exception:
                pages.append({"page_number": page_number, "text": "", "method": "failed",
                              "warnings": ["page_extraction_failed"]})
                continue
            method = "text"
            # Sparse text-only pages need no OCR. Blank pages keep their numbering.
            if len(text) < settings.ocr_text_threshold and image_page:
                if settings.ocr_enabled:
                    try:
                        extracted = (ocr or _ocr_page)(page, settings).strip()
                        if extracted:
                            if len(extracted) > len(text):
                                text, method = extracted, "ocr"
                        else:
                            warnings.append("ocr_empty")
                    except Exception:
                        warnings.append("ocr_unavailable_or_failed")
                else:
                    warnings.append("ocr_disabled")
            pages.append({"page_number": page_number, "text": text,
                          "method": method, "warnings": warnings})
    return pages
