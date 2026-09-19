"""Create original bilingual study material without touching existing PDFs."""
from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def create_sample(data_root: Path) -> Path:
    destination = data_root / "Example" / "Study-Basics" / "learning-notes.pdf"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Existing sample is preserved: {destination}")
    document = fitz.open()
    content = [
        ("1. Spaced repetition", "Spaced repetition means reviewing a topic at increasing intervals.\n"
         "For this sample course, review on day 1, day 3, and day 7.\n"
         "Retrieval practice means recalling an answer before looking at the notes.",
         "間隔反復は、復習の間隔を徐々に長くする学習方法です。\n"
         "このサンプルでは、１日後、３日後、７日後に復習します。\n"
         "答えを見る前に思い出す練習を、検索練習と呼びます。"),
        ("2. Explaining an idea", "A clear explanation defines the concept, gives an example,\n"
         "and checks the limits of that example. A mistake is evidence for revision.\n"
         "A useful question is: What evidence supports this explanation?",
         "説明では、概念を定義し、具体例を示し、例が当てはまる範囲を確認します。\n"
         "間違いは、説明を改善するための手がかりです。\n"
         "説明を支える根拠は何か、と問い直しましょう。"),
        ("3. Practice problem", "Question: Name the three review days used in this sample.\n"
         "Answer: Day 1, day 3, and day 7.\n"
         "Question: What should happen before looking at the answer?\n"
         "Answer: Try to recall it independently.",
         "練習問題：この教材の復習日はいつですか。\n"
         "解答：１日後、３日後、７日後です。\n"
         "練習問題：答えを見る前に何をしますか。\n"
         "解答：自分で思い出す練習をします。")]
    for number, (title, english, japanese) in enumerate(content, start=1):
        page = document.new_page(width=595, height=842)
        page.insert_text((52, 70), "STUDY WITH AI / ORIGINAL SAMPLE", fontsize=10, color=(0.2, 0.4, 0.5))
        page.insert_text((52, 112), title, fontsize=22)
        page.insert_text((52, 160), english, fontsize=12, lineheight=1.7)
        page.insert_text((52, 300), japanese, fontname="japan", fontsize=12, lineheight=1.9)
        page.insert_text((52, 795), f"Original synthetic material - no personal study data / {number}", fontsize=9)
    document.set_metadata({"title": "Study Basics - Original Sample", "author": "Study-with-AI"})
    document.save(destination)
    document.close()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("sample_data"))
    args = parser.parse_args()
    print(create_sample(args.data_root).resolve())


if __name__ == "__main__":
    main()
