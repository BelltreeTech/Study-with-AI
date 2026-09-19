"""Project-owned paths and learning policy. No global Codex configuration is edited."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = os.environ.get('STUDY_DATA_DIR', str(ROOT / 'data'))
USER_DATA_DIR = Path(os.environ.get('STUDY_STATE_DIR', str(ROOT / 'user_data')))
CACHE_DIR = Path(os.environ.get('STUDY_CACHE_DIR', str(ROOT / 'cache')))
LLM_MODEL = 'gpt-6-astra'
MODEL_EFFORT = 'medium'
EMBEDDING_MODEL = 'intfloat/multilingual-e5-small'
EMBEDDING_BATCH_SIZE = 32
OCR_TEXT_THRESHOLD = 50
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 5
QUIZ_TOP_K = 3
LECTURE_TOP_K = 10
SOCRATIC_HISTORY_LIMIT = 20
SOCRATIC_CONTEXT_LIMIT = 6000
PASS_SCORE_EASY = 70
PASS_SCORE_NORMAL = 80
PASS_SCORE_HARD = 90
PASS_SCORES = {'Easy': 70, 'Normal': 80, 'Hard': 90}
PROMPT_VERSION = 'study-2'
SCHEMA_VERSION = 'study-2'

@dataclass(frozen=True)
class LearningOptions:
    audience: str = '初心者向け (Beginner)'
    length: str = '普通 (Normal)'
    tutor_style: str = '標準（理論と具体例）'
    require_math: bool = False
    difficulty: str = 'Normal'
    top_k: int = 5

    def __post_init__(self) -> None:
        if self.difficulty not in PASS_SCORES or not 1 <= self.top_k <= 10:
            raise ValueError('難易度または検索件数が不正です。')
