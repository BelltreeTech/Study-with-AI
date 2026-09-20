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
PROMPT_VERSION = 'study-4'
SCHEMA_VERSION = 'study-3'
LEARNING_APPROACHES = ('体系的に理解', '例題を多く解く', '実践・プロジェクト', '試験に備える')
SESSION_MINUTES = (15, 25, 45, 60)
LEARNING_GOAL_MAX_LENGTH = 1200
PRIOR_KNOWLEDGE_MAX_LENGTH = 1200
ANALOGY_DOMAIN_MAX_LENGTH = 300

@dataclass(frozen=True)
class LearningOptions:
    audience: str = '初心者向け (Beginner)'
    length: str = '普通 (Normal)'
    tutor_style: str = '標準（理論と具体例）'
    require_math: bool = False
    difficulty: str = 'Normal'
    top_k: int = 5
    learning_goal: str = ''
    prior_knowledge: str = ''
    learning_approach: str = '体系的に理解'
    analogy_domain: str = ''
    session_minutes: int = 25
    time_scope: str = 'lecture_input'

    @classmethod
    def from_saved(cls, saved: dict) -> 'LearningOptions':
        """Missing scope in an existing saved profile means the legacy total."""
        if not isinstance(saved, dict):
            raise ValueError('保存された学習設定の形式が不正です。')
        if not saved:
            return cls()
        return cls(**({'time_scope': 'legacy_total'} | saved))

    def __post_init__(self) -> None:
        if self.difficulty not in PASS_SCORES or not 1 <= self.top_k <= 10:
            raise ValueError('難易度または検索件数が不正です。')
        for text, maximum, label in (
            (self.learning_goal, LEARNING_GOAL_MAX_LENGTH, '学習の目的'),
            (self.prior_knowledge, PRIOR_KNOWLEDGE_MAX_LENGTH, '前提知識'),
            (self.analogy_domain, ANALOGY_DOMAIN_MAX_LENGTH, 'たとえの分野'),
        ):
            if not isinstance(text, str) or len(text) > maximum:
                raise ValueError(f'{label}は{maximum}文字以内の文章で指定してください。')
        if self.learning_approach not in LEARNING_APPROACHES:
            raise ValueError('学び方は表示された選択肢から指定してください。')
        if type(self.session_minutes) is not int or self.session_minutes not in SESSION_MINUTES:
            raise ValueError('学習時間は15、25、45、60分のいずれかで指定してください。')
        if self.time_scope not in ('lecture_input', 'legacy_total'):
            raise ValueError('学習時間の対象が不正です。')
