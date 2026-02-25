"""
PDF読み込み・テキスト抽出モジュール。

PyMuPDF（fitz）を使用してPDFからページ単位でテキストを抽出する。
テキストが極端に少ない（画像PDF）場合は、OCRにフォールバックする。
"""

import fitz  # PyMuPDF

# OCRフォールバック用（画像PDF対応）
try:
    from pdf2image import convert_from_path
    import pytesseract

    _ocr_available: bool = True
except ImportError:
    _ocr_available = False

# 画像PDFと判断するテキスト文字数の閾値
k_ocrThreshold = 50


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """
    PDFファイルからページごとにテキストを抽出する。

    まずPyMuPDFでテキスト抽出を試み、抽出量が閾値以下の場合は
    OCR（pytesseract + pdf2image）にフォールバックする。

    Args:
        pdf_path: PDFファイルのパス

    Returns:
        各ページの情報を含む辞書のリスト。
        各辞書は {"page_number": int, "text": str} の形式。
    """
    # ---- 1. PyMuPDFでテキスト抽出を試行 ----
    pages: list[dict] = _extract_with_pymupdf(pdf_path)
    total_chars: int = sum(len(p["text"]) for p in pages)

    if total_chars > k_ocrThreshold:
        return pages

    # ---- 2. テキストが少ない → OCRフォールバック ----
    print(f"  [PDFReader] テキスト量が少ない（{total_chars}文字）。OCRモードに切替: {pdf_path}")

    if not _ocr_available:
        print("  [PDFReader] ⚠️ OCRライブラリ未インストール。テキスト抽出をスキップ。")
        if pages:
            return pages
        raise ValueError(f"画像PDFですがOCRライブラリが利用できません: {pdf_path}")

    ocr_pages: list[dict] = _extract_with_ocr(pdf_path)

    if ocr_pages:
        return ocr_pages

    # OCRでも取得できなかった場合、PyMuPDFの結果があればそれを返す
    if pages:
        return pages

    raise ValueError(f"PyMuPDF・OCR両方でテキストを抽出できませんでした: {pdf_path}")


def _extract_with_pymupdf(pdf_path: str) -> list[dict]:
    """PyMuPDFでPDFからテキストを抽出する。"""
    pages: list[dict] = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise FileNotFoundError(f"PDFファイルを開けません: {pdf_path} - {e}")

    for page_num in range(len(doc)):
        page = doc[page_num]
        text: str = page.get_text("text")

        # 空白のみのページはスキップ
        if text.strip():
            pages.append({
                "page_number": page_num + 1,  # 1-indexed
                "text": text.strip(),
            })

    doc.close()
    return pages


def _extract_with_ocr(pdf_path: str) -> list[dict]:
    """pdf2image + pytesseract でOCRテキスト抽出を行う。"""
    pages: list[dict] = []

    try:
        # PDFを画像に変換（Popplerはパスから自動検出）
        images = convert_from_path(pdf_path, dpi=300)
    except Exception as e:
        print(f"  [PDFReader] ⚠️ PDF→画像変換に失敗: {e}")
        return pages

    for i, image in enumerate(images):
        try:
            text: str = pytesseract.image_to_string(image, lang="jpn+eng")
        except Exception as e:
            print(f"  [PDFReader] ⚠️ OCR失敗（ページ{i + 1}）: {e}")
            continue

        if text.strip():
            pages.append({
                "page_number": i + 1,
                "text": text.strip(),
            })

    if pages:
        print(f"  [PDFReader] OCR完了: {len(pages)} ページ抽出")
    else:
        print(f"  [PDFReader] ⚠️ OCRでもテキストを抽出できませんでした")

    return pages


if __name__ == "__main__":
    # 動作確認用
    import sys

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "Deep Learning from Scratch (Seth Weidman).pdf"
    pages = extract_text_from_pdf(pdf_path)
    print(f"抽出ページ数: {len(pages)}")
    for p in pages[:3]:
        print(f"--- ページ {p['page_number']} (先頭200文字) ---")
        print(p["text"][:200])
