"""
システム全体の設定値を一元管理するモジュール。

各モジュールで使用される定数をここに集約し、
ハードコードされたマジックナンバーを排除する。
"""

from pathlib import Path

# ==============================================================
# ディレクトリ設定
# ==============================================================
DATA_DIR: str = "data"
CACHE_DIR: Path = Path("cache")
USER_DATA_DIR: Path = Path("user_data")

# ==============================================================
# LLM モデル設定
# ==============================================================
LLM_MODEL: str = "gpt-4o-mini"
EMBEDDING_MODEL: str = "text-embedding-3-small"

# ==============================================================
# Embedding 処理
# ==============================================================
EMBEDDING_BATCH_SIZE: int = 100

# ==============================================================
# PDF / OCR 処理
# ==============================================================
OCR_TEXT_THRESHOLD: int = 50  # これ以下のテキスト文字数で画像PDFと判定

# ==============================================================
# テキストチャンク分割
# ==============================================================
CHUNK_SIZE: int = 500
CHUNK_OVERLAP: int = 100

# ==============================================================
# RAG検索
# ==============================================================
DEFAULT_TOP_K: int = 5
QUIZ_TOP_K: int = 3      # 試験問題生成時のTop-K
LECTURE_TOP_K: int = 10   # 講義ノート生成時のTop-K

# ==============================================================
# LLM パラメータ (Temperature / Max Tokens)
# ==============================================================
# クエリ拡張
TEMPERATURE_QUERY_EXPANSION: float = 0.0
MAX_TOKENS_QUERY_EXPANSION: int = 200

# RAG回答生成
TEMPERATURE_RAG_ANSWER: float = 0.3
MAX_TOKENS_RAG_ANSWER: int = 1024

# 試験問題生成
TEMPERATURE_QUIZ: float = 0.7
MAX_TOKENS_QUIZ: int = 3000

# 採点
TEMPERATURE_GRADING: float = 0.3
MAX_TOKENS_GRADING: int = 3000

# ソクラテス対話
TEMPERATURE_SOCRATIC: float = 0.7
MAX_TOKENS_SOCRATIC: int = 1024
SOCRATIC_HISTORY_LIMIT: int = 20  # 対話履歴の最大件数
SOCRATIC_CONTEXT_LIMIT: int = 3000  # 講義コンテキストの最大文字数

# カリキュラム生成
TEMPERATURE_CURRICULUM: float = 0.7
MAX_TOKENS_CURRICULUM: int = 1024

# 講義ノート生成
TEMPERATURE_LECTURE: float = 0.4
MAX_TOKENS_LECTURE: int = 8000

# ==============================================================
# 試験 合格ライン
# ==============================================================
PASS_SCORE_EASY: int = 70
PASS_SCORE_NORMAL: int = 80
PASS_SCORE_HARD: int = 90

PASS_SCORES: dict[str, int] = {
    "Easy": PASS_SCORE_EASY,
    "Normal": PASS_SCORE_NORMAL,
    "Hard": PASS_SCORE_HARD,
}
