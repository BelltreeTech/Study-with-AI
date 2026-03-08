"""
テキストチャンク分割モジュール。

ページ単位のテキストを、RAG用の固定サイズチャンク（オーバーラップ付き）に分割する。

🧮 【チャンキングの必要性 — LLMのContext Window制限】
LLM（GPT-4等）には「一度に処理できるトークン数の上限」（Context Window）がある。
例: GPT-4o-mini は 128Kトークン ≈ 約50万文字を処理できるが、
検索精度の観点からは、短い「チャンク」の方がノイズが少なく精度が高い。

💡 【直感的意味】
教科書全体を丸ごと渡すのではなく、「関連するページだけ」を抜き出して渡す方が、
LLMは正確に回答できる。チャンキングは「教科書を見出しごとにカード化する」作業に相当する。

🧮 【オーバーラップの意味】
チャンク境界で文脈が切れることを防ぐため、隣接するチャンク間で
overlap文字分の重複を持たせる。これにより、文の途中で切れた場合でも、
次のチャンクにその文の続きが含まれる。
Sliding Window方式とも呼ばれ、Transformerの局所的Attention Windowとも類似する概念。
"""

from src.config import CHUNK_SIZE, CHUNK_OVERLAP


def _find_split_point(text: str, target_pos: int) -> int:
    """
    指定位置付近の自然な区切り点（文末・改行）を探す。

    target_posの前方で最も近い文境界を返す。
    見つからない場合はtarget_posをそのまま返す。

    💡 【直感的意味】
    文の途中で無理矢理切ると、検索やEmbeddingの精度が低下する。
    自然な区切り（段落、改行、句点）で分割することで、
    各チャンクが意味的にまとまった単位になる。
    """
    # target_posの前方で区切り文字を探す（最大100文字戻る）
    search_start = max(0, target_pos - 100)
    search_region = text[search_start:target_pos]

    # 優先度順に区切り文字を探す（段落区切り > 行区切り > 文末ピリオド）
    for delimiter in ["\n\n", "\n", ". ", "? ", "! "]:
        last_pos = search_region.rfind(delimiter)
        if last_pos != -1:
            return search_start + last_pos + len(delimiter)

    return target_pos


def chunk_text(
    pages: list[dict],
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """
    ページ群のテキストをチャンクに分割する。

    🧮 【アルゴリズム】
    各ページに対して:
    1. start = 0 から開始
    2. end = start + chunk_size で仮の終了位置を決定
    3. _find_split_point で自然な区切り点に補正
    4. text[start:end] をチャンクとして登録
    5. start = end - overlap で次の開始位置を計算（オーバーラップ分だけ戻る）
    6. テキスト末尾まで繰り返し

    📐 【出力データ構造】
    List[Dict] — 各要素:
    {
        "text": str,           — チャンクのテキスト本文
        "page_number": int,    — 元PDFのページ番号
        "chunk_index": int,    — 全チャンク通しのインデックス（0始まり）
        "source_file": str     — 元PDFのファイルパス（オプション）
    }

    💡 【DL概念との紐付け】
    チャンキングは、Transformerの「Tokenization」と類似する概念。
    Tokenizerがテキストを「サブワード単位」に分割するのに対し、
    Chunkerはテキストを「意味的な段落単位」に分割する。
    どちらも「長い入力を扱いやすい単位に分割する」前処理である。

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

        # 💡 Sliding Window方式でテキストを走査
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

            # 🧮 オーバーラップを考慮して次の開始位置を計算
            # 💡 end - overlap で「少し戻る」ことで、チャンク境界の文脈断裂を防ぐ
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
