"""
RAGシステム CLIエントリーポイント。

data/ ディレクトリ内のPDFファイルを選択し、対話的に質問応答を行う。
"""

import sys
from pathlib import Path

from src.core.rag_core import RAGCore


# PDFデータディレクトリ
k_dataDir = Path("data")


def _list_pdf_files() -> list[Path]:
    """
    data/ ディレクトリ内のPDFファイル一覧を返す。

    Returns:
        PDFファイルのPathオブジェクトリスト（名前順ソート済み）
    """
    if not k_dataDir.exists():
        print(f"エラー: {k_dataDir}/ ディレクトリが存在しません。")
        sys.exit(1)

    pdf_files: list[Path] = sorted(k_dataDir.glob("*.pdf"))

    if not pdf_files:
        print(f"エラー: {k_dataDir}/ ディレクトリにPDFファイルが見つかりません。")
        sys.exit(1)

    return pdf_files


def _select_pdfs(pdf_files: list[Path]) -> list[str]:
    """
    ユーザーにPDFファイルを選択させる。

    Args:
        pdf_files: 利用可能なPDFファイルリスト

    Returns:
        選択されたPDFファイルパスのリスト
    """
    print("📂 利用可能なPDFファイル:")
    print("-" * 60)
    for i, pdf_file in enumerate(pdf_files, 1):
        size_mb: float = pdf_file.stat().st_size / (1024 * 1024)
        print(f"  [{i}] {pdf_file.name} ({size_mb:.1f} MB)")
    print("-" * 60)

    # PDFが1つだけの場合は自動選択
    if len(pdf_files) == 1:
        print(f"PDFファイルが1つのみのため、自動選択します: {pdf_files[0].name}")
        return [str(pdf_files[0])]

    print("読み込むPDFの番号をカンマ区切りで入力してください（例: 1,3）")
    print("すべて選択する場合は 'all' と入力:")

    while True:
        try:
            user_input: str = input("\n📋 選択: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            sys.exit(0)

        if not user_input:
            continue

        # 全選択
        if user_input.lower() == "all":
            selected: list[str] = [str(f) for f in pdf_files]
            print(f"\n全 {len(selected)} ファイルを選択しました。")
            return selected

        # 番号指定
        try:
            indices: list[int] = [int(x.strip()) for x in user_input.split(",")]
            selected = []
            for idx in indices:
                if idx < 1 or idx > len(pdf_files):
                    print(f"  エラー: 番号 {idx} は範囲外です (1-{len(pdf_files)})")
                    break
                selected.append(str(pdf_files[idx - 1]))
            else:
                # ループが正常終了した場合（breakされなかった場合）
                print(f"\n{len(selected)} ファイルを選択しました:")
                for path in selected:
                    print(f"  - {Path(path).name}")
                return selected
        except ValueError:
            print("  エラー: 数字をカンマ区切りで入力してください（例: 1,3）")


def main() -> None:
    """メインの対話ループを実行する。"""
    print("=" * 60)
    print("  RAG System - PDF質問応答")
    print("  NumPyベースのベクトル検索（スクラッチ実装）")
    print("=" * 60)
    print()

    # PDF選択
    pdf_files: list[Path] = _list_pdf_files()
    selected_paths: list[str] = _select_pdfs(pdf_files)

    print()

    # パイプライン初期化（PDF読み込み・インデックス構築）
    try:
        pipeline = RAGCore(selected_paths)
    except Exception as e:
        print(f"エラー: パイプラインの初期化に失敗しました: {e}")
        sys.exit(1)

    print()
    print("準備完了！質問を入力してください（quit/exit で終了）")
    print("-" * 60)

    while True:
        try:
            question: str = input("\n📖 質問: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not question:
            continue

        if question.lower() in ("quit", "exit", "q"):
            print("終了します。")
            break

        print("\n🔍 検索・回答生成中...")
        result: dict = pipeline.query(question)

        # 回答の表示
        print("\n" + "=" * 60)
        print("📝 回答:")
        print("-" * 60)
        print(result["answer"])

        # 参照ソースの表示
        print("\n" + "-" * 60)
        print("📚 参照ソース:")
        for i, source in enumerate(result["sources"], 1):
            source_name: str = Path(source.get("source_file", "不明")).name
            print(
                f"  [{i}] {source_name} - ページ {source['page_number']} "
                f"(類似度: {source['similarity']:.4f})"
            )
            print(f"      {source['text_preview']}")
        print("=" * 60)


if __name__ == "__main__":
    main()
