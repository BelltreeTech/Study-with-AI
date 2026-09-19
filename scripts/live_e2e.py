"""Opt-in, synthetic-only Codex learning E2E with a durable eight-job ceiling.

No login/browser action is performed. --check-only never generates. Outputs,
ledger and human review stay in the ignored .study-runtime/phase2-live directory.
A job reservation counts even if interrupted before launch: the limit is on
additional application jobs, not CLI HTTP attempts or service-side inference.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402

from src import progress  # noqa: E402
from src.codex_provider import CodexProvider  # noqa: E402
from src.config import LLM_MODEL, MODEL_EFFORT, LearningOptions  # noqa: E402
from src.jobs import TERMINAL_STATES, JobManager  # noqa: E402
from src.learning_repository import LearningRepository  # noqa: E402
from src.materials import save_pdf  # noqa: E402
from src.repository import Repository, canonical_json, ensure_private_database_file, now_iso  # noqa: E402
from src.retriever import LocalRetriever  # noqa: E402
from src.schemas import validate_schema  # noqa: E402
from src.service import LearningRequest, StudyService  # noqa: E402

OPERATIONS = ('probe', 'answer', 'curriculum', 'lecture', 'dialogue', 'quiz', 'grade')
MAX_JOBS = 8
SUBJECT = 'Synthetic/Phase2-Learning'
SESSION = 'phase2-synthetic-session-v1'
COURSE = 'phase2-synthetic-course-v1'
IDENTITY = 'study-with-ai-phase2-synthetic-v1'
PROBE_SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean', 'enum': [True]}},
                'required': ['ok'], 'additionalProperties': False}
REVIEW_CHECKS = ('rag_source_support', 'lecture_source_support', 'dialogue_relevance',
                 'question_alignment', 'partial_wrong_grading', 'grading_reasoning',
                 'citations_and_pages', 'completion_and_restart')
TEXTBOOK = '''Synthetic study note: retrieval practice and spaced repetition.
Retrieval practice means trying to recall information from memory before looking at the answer.
Rereading alone is not retrieval practice. Checking an answer afterwards provides corrective feedback.
Spaced repetition separates review sessions across time rather than cramming into one uninterrupted session.
A simple example is reviewing on day 1, day 3 and day 7, with intervals adjusted after errors.
These example intervals are not a universal optimal schedule. Learning depends on the material and the learner.
Combining recall, corrective feedback and later review can improve retention.
A learner who cannot recall a concept should revisit the explanation and try another retrieval attempt.
'''
JAPANESE_NOTE = '''検索練習・想起練習では、解答を見る前に記憶から答えを思い出します。
読むだけの復習とは異なり、思い出した後に解答と比べて誤りを修正します。
間隔反復では復習を時間的に分散します。一度に詰め込むこととは異なります。
この教材の例は１日後、３日後、７日後です。すべての学習者に最適とは限りません。
思い出せなかった概念は説明を見直し、もう一度思い出す練習を行います。
'''


class Provider(Protocol):
    def diagnostics(self) -> dict[str, Any]: ...
    def generate(self, prompt: str, schema: dict, cancel_event: threading.Event | None = None) -> dict: ...
    def probe_model(self, prompt: str, schema: dict, cancel_event: threading.Event | None = None) -> dict: ...


class HarnessHalted(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise HarnessHalted('unsafe_path', 'symlinkへの出力を拒否しました。')
    fd, name = tempfile.mkstemp(prefix='.phase2-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Workspace:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).absolute()
        self.root = self.project_root / '.study-runtime' / 'phase2-live'
        # Never allow a configured state/material path to redirect this harness.
        for path in (self.project_root, self.project_root / '.study-runtime', self.root):
            if path.is_symlink():
                raise HarnessHalted('unsafe_path', '専用合成保存先のsymlinkを拒否しました。')
        self.data = self.root / 'data'
        self.state = self.root / 'state'
        self.cache = self.root / 'cache'
        self.ledger_path = self.state / 'live-budget.sqlite3'
        self.jobs_path = self.state / 'jobs.sqlite3'

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = self.root / 'synthetic-owner.json'
        lock_path = self.root / '.run.lock'
        if lock_path.is_symlink():
            raise HarnessHalted('unsafe_path', '専用lockのsymlinkを拒否しました。')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HarnessHalted('already_running', '同じ実検証がすでに実行中です。') from exc
            if marker.exists():
                if marker.is_symlink() or json.loads(marker.read_text()).get('owner') != IDENTITY:
                    raise HarnessHalted('wrong_owner', '既存保存先の所有情報が一致しません。')
                if not self.ledger_path.is_file() or self.ledger_path.is_symlink() or self.ledger_path.stat().st_size == 0:
                    raise HarnessHalted('ledger_missing', '既存runの予算ledgerが欠落しています。予算を再初期化しません。')
                with sqlite3.connect(f'file:{self.ledger_path}?mode=ro', uri=True) as db:
                    version = db.execute("SELECT value FROM live_meta WHERE key='version'").fetchone()
                    if version is None or version[0] != '1':
                        raise HarnessHalted('ledger_version', '既存runの予算ledgerを確認できません。')
                    db.execute('SELECT operation FROM live_operations LIMIT 1')
            else:
                if any(path.name != '.run.lock' for path in self.root.iterdir()):
                    raise HarnessHalted('wrong_owner', '既存の非空保存先は初期化しません。')
                atomic_json(marker, {'owner': IDENTITY, 'created_at': now_iso(), 'synthetic_only': True})
            for folder in (self.data, self.state, self.cache, self.root / 'results'):
                if folder.is_symlink():
                    raise HarnessHalted('unsafe_path', '専用保存先のsymlinkを拒否しました。')
                folder.mkdir(exist_ok=True, mode=0o700)
            for filename in self.root.rglob('*'):
                if filename.is_symlink():
                    raise HarnessHalted('unsafe_path', '状態ファイルのsymlinkを拒否しました。')
            if (self.state / 'progress.json').exists():
                raise HarnessHalted('unexpected_legacy', '実検証保存先の旧進捗JSONを移行しません。')
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def material(self) -> None:
        path = self.data / SUBJECT / 'synthetic-note.pdf'
        if any(candidate.is_file() and candidate != path for candidate in self.data.rglob('*')):
            raise HarnessHalted('unexpected_material', '既知の合成教材以外はこの検証で使用しません。')
        manifest_path = self.root / 'material-manifest.json'
        if path.exists():
            if path.is_symlink() or not manifest_path.is_file():
                raise HarnessHalted('material_changed', '合成教材の所有情報が確認できません。')
            manifest = json.loads(manifest_path.read_text())
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get('sha256'):
                raise HarnessHalted('material_changed', '保存済み合成教材が変更されています。再生成しません。')
            return
        if manifest_path.exists():
            raise HarnessHalted('material_missing', '保存済み合成教材が欠落しています。再作成しません。')
        document = fitz.open()
        try:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(45, 45, 555, 450), TEXTBOOK, fontsize=11)
            page.insert_textbox(fitz.Rect(45, 470, 555, 790), JAPANESE_NOTE, fontname='japan', fontsize=11)
            raw = document.tobytes()
        finally:
            document.close()
        save_pdf(self.data, SUBJECT, path.name, raw)
        atomic_json(manifest_path, {'fixture': IDENTITY, 'sha256': hashlib.sha256(raw).hexdigest(),
                                    'relative_path': str(path.relative_to(self.root)), 'pages': 1})


class Budget:
    """Reservations are durable and conservative; failed jobs never free a slot."""
    def __init__(self, path: Path):
        self.path = path
        ensure_private_database_file(path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            row = db.execute("SELECT value FROM live_meta WHERE key='version'").fetchone()
            if row and row[0] != '1':
                raise HarnessHalted('ledger_version', '未対応の実検証ledgerです。')
            db.execute("INSERT OR IGNORE INTO live_meta VALUES ('version','1')")
            db.execute('''CREATE TABLE IF NOT EXISTS live_operations (
                operation TEXT NOT NULL, attempt INTEGER NOT NULL, request_id TEXT UNIQUE NOT NULL,
                request TEXT NOT NULL, status TEXT NOT NULL, job_id TEXT, result TEXT,
                error_code TEXT, retry_evidence TEXT, created_at TEXT NOT NULL,
                PRIMARY KEY(operation,attempt))''')

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def rows(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM live_operations ORDER BY created_at,operation,attempt')]

    def latest(self, operation: str) -> dict | None:
        with self.connect() as db:
            row = db.execute('SELECT * FROM live_operations WHERE operation=? ORDER BY attempt DESC LIMIT 1', (operation,)).fetchone()
            return dict(row) if row else None

    def reserve(self, operation: str, request: dict, *, evidence: str | None = None) -> dict:
        if operation not in OPERATIONS:
            raise ValueError('Unknown live operation')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT operation,attempt,status FROM live_operations').fetchall()
            prior = [row for row in rows if row['operation'] == operation]
            if len(rows) >= MAX_JOBS:
                raise HarnessHalted('budget_exhausted', '追加生成ジョブ8件の上限に達しました。')
            if prior:
                if not evidence or len(evidence.strip()) < 15:
                    raise HarnessHalted('retry_evidence_required', '再実行には具体的な修正根拠を明示してください。')
                if any(row['attempt'] > 1 for row in rows):
                    raise HarnessHalted('reserve_exhausted', '予備の再実行1件はすでに使用済みです。')
            elif evidence:
                raise HarnessHalted('no_failed_operation', '初回操作に予備枠は使用できません。')
            attempt = max((row['attempt'] for row in prior), default=0) + 1
            request_id = request['request_id']
            db.execute('INSERT INTO live_operations VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (operation, attempt, request_id, canonical_json(request), 'reserved', None, None, None, evidence, now_iso()))
        result = self.latest(operation)
        assert result is not None
        return result

    def update(self, row: dict, **values: Any) -> None:
        allowed = {'status', 'job_id', 'result', 'error_code'}
        if not values or set(values) - allowed:
            raise ValueError('Invalid ledger update')
        with self.connect() as db:
            columns = ','.join(f'{key}=?' for key in values)
            db.execute(f'UPDATE live_operations SET {columns} WHERE operation=? AND attempt=?',
                       (*values.values(), row['operation'], row['attempt']))

    def bind_runtime(self, info: dict) -> None:
        binding = canonical_json({key: info.get(key) for key in ('executable', 'version', 'codex_home', 'model', 'effort')})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM live_meta WHERE key='runtime'").fetchone()
            if row and row[0] != binding:
                raise HarnessHalted('runtime_changed', '実行環境が前回と異なります。既存ledgerを保持して確認してください。')
            db.execute("INSERT OR IGNORE INTO live_meta VALUES ('runtime',?)", (binding,))


@contextmanager
def synthetic_progress(workspace: Workspace) -> Iterator[None]:
    """This standalone harness has no UI thread; every progress call is scoped here."""
    original_dir, original_file = progress.k_progressDir, progress.k_progressFile
    progress.k_progressDir = workspace.state
    progress.k_progressFile = workspace.state / 'progress.json'
    try:
        yield
    finally:
        progress.k_progressDir, progress.k_progressFile = original_dir, original_file


def partial_answer(exam: dict) -> tuple[str, str]:
    """Copy nine reference answers; give an explicit misconception for the last."""
    wrong_id = exam['questions'][-1]['id']
    answers = []
    for question in exam['questions']:
        answer = question['model_answer']
        if question['id'] == wrong_id:
            answer = ('Retrieval practice means only passively rereading while never attempting recall. '
                      'Spaced repetition requires all reviews in one uninterrupted cramming session. '
                      'Corrective feedback should never be checked.')
        answers.append(f"{question['id']}: {answer}")
    return '\n\n'.join(answers), wrong_id


class LiveHarness:
    def __init__(self, project_root: Path, provider: Provider | None = None):
        self.workspace = Workspace(project_root)
        self.provider: Provider = provider if provider is not None else cast(Provider, CodexProvider())

    def check(self) -> dict:
        info = self.provider.diagnostics()
        return {'generation_jobs_started_by_check': 0, 'workspace': str(self.workspace.root),
                'maximum_application_jobs': MAX_JOBS, 'diagnostics': info,
                'resume_command': '.venv/bin/python scripts/live_e2e.py --run --confirm-live'}

    def _request(self, operation: str, service: StudyService, results: dict) -> dict:
        if operation == 'probe':
            return {'request_id': uuid.uuid4().hex, 'kind': 'probe', 'model': LLM_MODEL,
                    'effort': MODEL_EFFORT, 'prompt': 'Return the JSON object {"ok":true}. No tools or actions.',
                    'schema': PROBE_SCHEMA}
        payloads: dict[str, dict] = {
            'answer': {'question': 'Briefly explain retrieval practice and spaced repetition, citing the supplied note.'},
            'curriculum': {'topic': 'Retrieval practice and spaced repetition: five very short chapters.', 'chapter_count': 5},
        }
        if operation in ('lecture', 'dialogue', 'quiz'):
            chapter = results['curriculum']['chapters'][0]
            payloads['lecture'] = {'title': chapter['title'] + ' / retrieval practice and spaced repetition', 'description': chapter['description'] + ' Keep the lecture short.'}
            if operation != 'lecture':
                lecture = results['lecture']
                payloads['dialogue'] = {'question': 'How is active recall different from passive rereading?',
                                        'lecture': lecture['markdown'], 'lecture_revision': lecture['material_revision']}
                payloads['quiz'] = {'topic': chapter['title'] + ' / retrieval practice and spaced repetition; keep questions and model answers short', 'lecture': lecture['markdown'],
                                   'lecture_revision': lecture['material_revision'], 'chapter_index': 0,
                                   'lecture_id': lecture['lecture_id']}
        if operation == 'grade':
            answer, _ = partial_answer(results['quiz'])
            payloads['grade'] = {'exam': results['quiz'], 'answer': answer}
        options = LearningOptions(length='簡潔 (Concise)', top_k=2, difficulty='Normal',
                                  tutor_style='ソクラテス・スパルタ' if operation == 'dialogue' else '標準（理論と具体例）')
        request = service.prepare(operation, SUBJECT, SESSION, payloads[operation], options,
                                  course_id=COURSE if operation in ('lecture', 'dialogue', 'quiz', 'grade') else '')
        return request.to_dict()

    def _existing_job(self, row: dict, manager: JobManager) -> dict | None:
        job_id = row['job_id']
        if not job_id:
            with sqlite3.connect(self.workspace.jobs_path) as db:
                existing = db.execute('SELECT id FROM jobs WHERE idempotency_key=?', (row['request_id'],)).fetchone()
                job_id = existing[0] if existing else None
        return manager.get(job_id) if job_id else None

    def _apply(self, operation: str, row: dict, result: dict, store: LearningRepository) -> None:
        event = 'phase2-live:' + row['request_id']
        if operation == 'curriculum':
            progress.commit_learning_event(COURSE, event, curriculum=result['chapters'], current_chapter_index=0,
                                           metadata={'subject': SUBJECT, 'title': 'Synthetic Phase2 course', 'course_id': COURSE})
        elif operation == 'lecture':
            result['lecture_id'] = row['request_id']
            def save(data: dict) -> None:
                data['courses'][COURSE]['curriculum'][0]['lecture_content'] = result
            progress.get_repository().update(save, event_id=event, fingerprint=hashlib.sha256(canonical_json(result).encode()).hexdigest())
        elif operation == 'grade':
            progress.commit_learning_event(COURSE, event, grading_result=result, weaknesses=result.get('weaknesses', []))
            if result['passed']:
                progress.complete_chapter(COURSE, 0, result['attempt_id'], material_revision=result['material_revision'])
        store.apply_result(event, IDENTITY, {operation: result})

    def run(self, *, confirm_live: bool, retry_operation: str | None = None, retry_evidence: str | None = None) -> dict:
        if not confirm_live:
            raise HarnessHalted('opt_in_required', '--run --confirm-live の明示指定が必要です。')
        if (retry_operation is None) != (retry_evidence is None):
            raise HarnessHalted('retry_evidence_required', '再実行対象と根拠を両方指定してください。')
        with self.workspace.lock(), synthetic_progress(self.workspace):
            budget = Budget(self.workspace.ledger_path)
            complete = all((row := budget.latest(op)) and row['status'] == 'succeeded' for op in OPERATIONS)
            if complete and not retry_operation:
                self.workspace.material()
                # Restore receipts even if a process died after persisting a result
                # but before updating progress. No diagnostics or generation.
                store = LearningRepository(self.workspace.state / 'learning.sqlite3')
                for operation in OPERATIONS:
                    row = budget.latest(operation)
                    assert row is not None
                    self._apply(operation, row, json.loads(row['result']), store)
                return self.report(budget)
            info = self.provider.diagnostics()
            if info.get('auth') != 'chatgpt' or info.get('model') != LLM_MODEL or info.get('effort') != MODEL_EFFORT:
                raise HarnessHalted('preflight_failed', '指定モデル・medium・ChatGPT認証を確認できません。生成を開始しません。')
            if not info.get('boundary_verified') or not info.get('probe_ready', info.get('ready', False)):
                raise HarnessHalted('preflight_failed', '認証・実行境界の診断が未完了です。生成を開始しません。')
            previous_probe = budget.latest('probe')
            if previous_probe and previous_probe['status'] == 'succeeded' and not info.get('ready') and retry_operation != 'probe':
                raise HarnessHalted('probe_resume_required', 'catalog未確認の再起動後は、根拠付きの明示probe再検証が必要です。自動再実行はしません。')
            if previous_probe and previous_probe['status'] == 'succeeded' and not info.get('ready') and retry_operation == 'probe':
                if any(row['operation'] != 'probe' and row['status'] != 'succeeded' for row in budget.rows()):
                    raise HarnessHalted('insufficient_reserve', 'probe再検証と失敗操作の再実行には予備枠が2件必要です。上限を保つため停止します。')
            if retry_operation:
                previous = budget.latest(retry_operation)
                may_reprobe = retry_operation == 'probe' and not info.get('ready')
                if not previous or (previous['status'] == 'succeeded' and not may_reprobe):
                    raise HarnessHalted('retry_not_required', 'この操作の再実行を正当化する失敗または未確認状態がありません。')
            budget.bind_runtime(info)
            atomic_json(self.workspace.root / 'diagnostics.json', info)
            self.workspace.material()
            service = StudyService(self.provider, LocalRetriever(self.workspace.data, self.workspace.cache))
            store = LearningRepository(self.workspace.state / 'learning.sqlite3')
            results: dict[str, dict] = {}
            with JobManager(self.workspace.jobs_path) as manager:
                for operation in OPERATIONS:
                    row = budget.latest(operation)
                    reprobe = (operation == 'probe' and row and row['status'] == 'succeeded'
                               and not info.get('ready') and retry_operation == 'probe')
                    if row and row['status'] == 'succeeded' and not reprobe:
                        result = json.loads(row['result'])
                        self._apply(operation, row, result, store)
                        results[operation] = result
                        continue
                    if row and row['status'] not in ('failed', 'interrupted') and not reprobe:
                        existing = self._existing_job(row, manager)
                        if existing and existing['state'] == 'succeeded':
                            result = existing['result']
                            if operation == 'lecture':
                                result['lecture_id'] = row['request_id']
                            atomic_json(self.workspace.root / 'results' / f'{operation}.json', result)
                            budget.update(row, status='succeeded', job_id=existing['id'], result=canonical_json(result))
                            self._apply(operation, row, result, store)
                            results[operation] = result
                            continue
                        state = existing['state'] if existing else 'interrupted'
                        budget.update(row, status=state if state in ('failed', 'cancelled', 'interrupted') else 'interrupted',
                                      error_code=existing.get('error_code') if existing else 'interrupted')
                        row = budget.latest(operation)
                    if row and retry_operation != operation:
                        self.report(budget)
                        raise HarnessHalted('prior_failure', f'{operation}は前回中断/失敗しました。根拠なしで再生成しません。')
                    if operation != 'probe' and not info.get('ready') and not results.get('probe'):
                        raise HarnessHalted('probe_required', '同じ実行環境での明示probeが必要です。')
                    request = self._request(operation, service, results)
                    row = budget.reserve(operation, request, evidence=retry_evidence if row else None)
                    worker: Callable[[threading.Event], dict]
                    if operation == 'probe':
                        def probe_worker(event: threading.Event) -> dict:
                            value = self.provider.probe_model(request['prompt'], request['schema'], event)
                            validate_schema(value, PROBE_SCHEMA)
                            return value
                        worker = probe_worker
                    else:
                        prepared = LearningRequest.from_dict(request)
                        def learning_worker(event: threading.Event, req: LearningRequest = prepared) -> dict:
                            return service.execute(req, event)
                        worker = learning_worker
                    job_id = manager.submit(operation, {'run': IDENTITY, 'operation': operation}, request, request['request_id'], worker)
                    budget.update(row, status='submitted', job_id=job_id)
                    # Includes time waiting for a previous process's generation lock.
                    # The Provider also enforces its own total subprocess deadline.
                    job_deadline = time.monotonic() + 240
                    while True:
                        if time.monotonic() >= job_deadline:
                            manager.cancel(job_id)
                        job = manager.get(job_id)
                        assert job is not None
                        if job['state'] in TERMINAL_STATES:
                            break
                        time.sleep(.05)
                    if job['state'] != 'succeeded':
                        budget.update(row, status=job['state'], error_code=job['error_code'])
                        self.report(budget)
                        raise HarnessHalted(job['error_code'] or job['state'], f'{operation}が失敗したため停止しました。自動再実行はしません。')
                    result = job['result']
                    if operation == 'lecture':
                        result['lecture_id'] = row['request_id']
                    budget.update(row, status='succeeded', result=canonical_json(result))
                    atomic_json(self.workspace.root / 'results' / f'{operation}.json', result)
                    self._apply(operation, row, result, store)
                    results[operation] = result
                    self.report(budget)
            return self.report(budget)

    def report(self, budget: Budget) -> dict:
        rows = budget.rows()
        latest = {op: budget.latest(op) for op in OPERATIONS}
        successful = {op: json.loads(row['result']) for op, row in latest.items() if row and row['status'] == 'succeeded'}
        grade, quiz = successful.get('grade'), successful.get('quiz')
        partial = None
        if grade and quiz:
            _, wrong_id = partial_answer(quiz)
            item = next(item for item in grade['items'] if item['question_id'] == wrong_id)
            partial = {'wrong_question_id': wrong_id, 'points': item['points'], 'max_points': item['max_points'],
                       'reduced_score_observed': item['points'] < item['max_points'], 'total': grade['score'],
                       'passed': grade['passed'], 'human_grading_review_required': True,
                       'answer_construction': 'Reference answers for all but the last question; explicit misconception for the last.',
                       'independent_accuracy_benchmark': False}
        review_path = self.workspace.root / 'manual-review.json'
        review = json.loads(review_path.read_text()) if review_path.is_file() and not review_path.is_symlink() else None
        result_digest = hashlib.sha256(canonical_json(successful).encode()).hexdigest()
        quality_accepted = bool(review and review.get('result_digest') == result_digest and review.get('reviewer') and review.get('reviewed_at') and all(
            review.get('checks', {}).get(key, {}).get('status') == 'pass'
            and len(review['checks'][key].get('evidence', '').strip()) >= 20 for key in REVIEW_CHECKS))
        completed = len(successful) == len(OPERATIONS)
        report = {'synthetic_only': True, 'model_requested': LLM_MODEL, 'effort_requested': MODEL_EFFORT,
                  'maximum_application_jobs': MAX_JOBS, 'reserved_jobs': len(rows),
                  'submitted_jobs': sum(row['job_id'] is not None for row in rows),
                  'cli_internal_attempts': 'unknown', 'server_inference_count': 'unknown',
                  'operations': [{key: row[key] for key in ('operation', 'attempt', 'status', 'job_id', 'error_code', 'retry_evidence')} for row in rows],
                  'technical_flow_completed': completed, 'partial_wrong_grading': partial,
                  'educational_quality': 'accepted_by_manual_evidence' if completed and quality_accepted and partial and partial['reduced_score_observed'] else 'manual_review_required',
                  'review_result_digest': result_digest,
                  'schema_success_is_not_educational_quality': True, 'generated_at': now_iso()}
        if (self.workspace.state / 'progress.sqlite3').is_file():
            state = Repository(self.workspace.state / 'progress.sqlite3').read()
            report['synthetic_total_exp'] = state.get('user_profile', {}).get('total_exp', 0)
            report['chapter_completed'] = bool(state['courses'].get(COURSE, {}).get('curriculum', [{}])[0].get('status') == 'completed')
        atomic_json(self.workspace.root / 'report.json', report)
        template = self.workspace.root / 'manual-review-template.json'
        if not template.exists():
            atomic_json(template, {'reviewer': '', 'reviewed_at': '', 'result_digest': result_digest,
                'instructions': '現在のreport.jsonのreview_result_digestを確認し、各evidenceに具体的な教材ページ・主張・設問ID・配点の照合根拠を記入。完成後manual-review.jsonへ保存。', 'checks': {
                key: {'status': 'not_reviewed', 'evidence': ''} for key in REVIEW_CHECKS}})
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--confirm-live', action='store_true', help='Allow up to eight additional application jobs; consumes account usage')
    parser.add_argument('--retry-operation', choices=OPERATIONS)
    parser.add_argument('--retry-evidence', help='Specific verified cause/fix justifying the single reserve job')
    args = parser.parse_args(argv)
    harness = LiveHarness(Path(__file__).resolve().parents[1])
    try:
        result = harness.check() if args.check_only else harness.run(confirm_live=args.confirm_live,
                    retry_operation=args.retry_operation, retry_evidence=args.retry_evidence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (HarnessHalted, ValueError, RuntimeError, OSError) as exc:
        print(json.dumps({'status': 'halted', 'code': getattr(exc, 'code', 'validation_error'), 'message': str(exc),
                          'automatic_retry': False}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
