"""
テキストチャンク分割モジュール。

ページ単位のテキストを、RAG用の固定サイズチャンク（オーバーラップ付き）に分割する。
"""


def _find_split_point(text: str, target_pos: int) -> int:
    """
    指定位置付近の自然な区切り点（文末・改行）を探す。

    target_posの前方で最も近い文境界を返す。
    見つからない場合はtarget_posをそのまま返す。
    """
    # target_posの前方で区切り文字を探す（最大100文字戻る）
    search_start = max(0, target_pos - 100)
    search_region = text[search_start:target_pos]

    # 優先度順に区切り文字を探す
    for delimiter in ["\n\n", "\n", ". ", "? ", "! "]:
        last_pos = search_region.rfind(delimiter)
        if last_pos != -1:
            return search_start + last_pos + len(delimiter)

    return target_pos


def chunk_text(
    pages: list[dict],
    chunk_size: int = 500,
    overlap: int = 100,
) -> list[dict]:
    """
    ページ群のテキストをチャンクに分割する。

    Args:
        pages: pdf_reader.extract_text_from_pdf()の出力
        chunk_size: 各チャンクの目標文字数
        overlap: チャンク間のオーバーラップ文字数

    Returns:
        チャンク情報の辞書リスト。
        各辞書は {"text": str, "page_number": int, "chunk_index": int, "source_file": str} の形式。
        source_fileはページ情報に含まれる場合のみ付与される。
    """
    chunks: list[dict] = []
    chunk_index: int = 0

    for page in pages:
        text: str = page["text"]
        page_number: int = page["page_number"]
        source_file: str = page.get("source_file", "")
        start: int = 0

        while start < len(text):
            end: int = start + chunk_size

            if end < len(text):
                # 文の途中で切れないよう、自然な区切り点を探す
                end = _find_split_point(text, end)

            chunk_text_content: str = text[start:end].strip()

            if chunk_text_content:
                chunk_data: dict = {
                    "text": chunk_text_content,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                }
                if source_file:
                    chunk_data["source_file"] = source_file
                chunks.append(chunk_data)
                chunk_index += 1

            # オーバーラップを考慮して次の開始位置を計算
            start = max(start + 1, end - overlap)

    return chunks


if __name__ == "__main__":
    # 動作確認用
    from pdf_reader import extract_text_from_pdf

    pages = extract_text_from_pdf("Deep Learning from Scratch (Seth Weidman).pdf")
    chunks = chunk_text(pages)
    print(f"チャンク数: {len(chunks)}")
    if chunks:
        print(f"\n--- チャンク0 (ページ{chunks[0]['page_number']}) ---")
        print(chunks[0]["text"][:300])
