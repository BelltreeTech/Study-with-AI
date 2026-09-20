"""Private, versioned SQLite learning documents and atomic submission claims."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.repository import ensure_private_database_file, sqlite_initialization_lock
from src.schemas import public_exam

SCHEMA_VERSION = 1


class LearningRepository:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create privately *before* SQLite creates either the main DB or WAL/SHM.
        # The same lock is used by other local repositories during initial setup.
        with sqlite_initialization_lock(self.path):
            ensure_private_database_file(self.path)
            self.path.chmod(0o600)
            with self.connect() as db:
                if db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                    db.execute('PRAGMA journal_mode=WAL')
                db.execute('BEGIN IMMEDIATE')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, SCHEMA_VERSION):
                    raise RuntimeError('この学習履歴DBのバージョンには未対応です。書き換えを停止しました。')
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                expected = {'learning_documents', 'learning_receipts'}
                if version == SCHEMA_VERSION and not expected.issubset(tables):
                    raise RuntimeError('学習履歴DBのテーブルが欠落しています。空データへの置換を停止しました。')
                if version == 0:
                    if tables:
                        raise RuntimeError('未識別の既存DBを学習履歴として初期化できません。')
                    db.execute('''CREATE TABLE learning_documents (
                        scope TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL,
                        PRIMARY KEY(scope, name))''')
                    db.execute('''CREATE TABLE learning_receipts (
                        job_id TEXT PRIMARY KEY, scope TEXT NOT NULL, applied_at TEXT NOT NULL)''')
                    db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            db.execute('PRAGMA busy_timeout=30000')
            with db:
                yield db
        except sqlite3.Error as exc:
            raise RuntimeError('学習履歴DBを読み書きできません。元データを保持して停止しました。') from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _write(db: sqlite3.Connection, scope: str, name: str, value: Any) -> None:
        db.execute('INSERT INTO learning_documents VALUES (?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',
                   (scope, name, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def get(self, scope: str, name: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?', (scope, name)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, scope: str, name: str, value: Any) -> None:
        with self.connect() as db:
            self._write(db, scope, name, value)

    def update_document(self, scope: str, name: str, update: Callable[[Any], Any], *, mirror_name: str | None = None) -> Any:
        """Read, compare and update one document under the existing write lock.

        The callback must not perform generation or access this repository again.
        Exceptions roll back without replacing the original document.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?',
                             (scope, name)).fetchone()
            value = update(json.loads(row[0]) if row else None)
            self._write(db, scope, name, value)
            if mirror_name is not None:
                self._write(db, scope, mirror_name, value)
            return value

    def claim_submission(self, scope: str, prepare_and_submit: Callable[[], str],
                         is_active: Callable[[str], bool]) -> tuple[str, bool]:
        """Serialize each scope's check + job submission + pending pointer.

        Prepare retrieval/input outside this method. The callback should only
        perform the short job-DB submit. is_active decides whether a succeeded
        but not-yet-applied job also blocks replacement. Callbacks must not write to
        this LearningRepository again while holding this lock.
        """
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?', (scope, 'pending')).fetchone()
            pending = json.loads(row[0]) if row else None
            if pending:
                if not isinstance(pending, str):
                    raise ValueError('保存済みジョブIDが不正です。')
                if is_active(pending):
                    return pending, False
            job_id = prepare_and_submit()
            if not isinstance(job_id, str) or not job_id:
                raise ValueError('新しいジョブIDが不正です。')
            self._write(db, scope, 'pending', job_id)
            return job_id, True

    def clear_pending(self, scope: str, expected_job_id: str) -> bool:
        """Clear only the job this tab observed, never a newer tab's submission."""
        if not isinstance(expected_job_id, str) or not expected_job_id:
            raise ValueError('解除対象のジョブIDが不正です。')
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE learning_documents SET value='null' WHERE scope=? AND name='pending' AND value=?",
                (scope, json.dumps(expected_job_id, ensure_ascii=False, allow_nan=False)),
            )
            return cursor.rowcount == 1

    def reset_exam(self, scope: str, expected_attempt_id: str, is_active: Callable[[str], bool]) -> bool:
        """Compare, archive public questions and clear an attempt atomically.

        The same write lock as claim_submission prevents another tab from
        submitting a grade or replacing the exam between these operations.
        is_active may only read the job repository, never write this repository.
        """
        if not isinstance(expected_attempt_id, str) or not expected_attempt_id:
            raise ValueError('終了する試験のIDが不正です。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')

            def read(name: str, default: Any = None) -> Any:
                row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?',
                                 (scope, name)).fetchone()
                return json.loads(row[0]) if row else default

            current = read('quiz')
            if not isinstance(current, dict) or current.get('attempt_id') != expected_attempt_id:
                return False
            pending = read('pending')
            if pending:
                if not isinstance(pending, str):
                    raise ValueError('保存済みジョブIDが不正です。')
                if is_active(pending):
                    return False
            answer = read('answer_draft:' + expected_attempt_id, '')
            if not isinstance(answer, str):
                raise ValueError('保存済み答案の形式が不正です。元データを保持して停止しました。')
            if answer:
                archived = read('answer_archive', [])
                if not isinstance(archived, list) or any(
                    not isinstance(item, dict) or not isinstance(item.get('attempt_id'), str) for item in archived
                ):
                    raise ValueError('保存済み答案一覧の形式が不正です。元データを保持して停止しました。')
                if not any(item['attempt_id'] == expected_attempt_id for item in archived):
                    try:
                        visible_exam = public_exam(current)
                    except (KeyError, TypeError) as exc:
                        raise ValueError('保存済み問題の形式が不正です。元データを保持して停止しました。') from exc
                    archived.append({'attempt_id': expected_attempt_id, 'exam': visible_exam, 'answer': answer})
                    self._write(db, scope, 'answer_archive', archived)
            self._write(db, scope, 'quiz', None)
            self._write(db, scope, 'grade', None)
            return True

    def append_session(self, registry_scope: str, session_id: str) -> list[str]:
        """Append to the latest registry under one transaction, preserving peers."""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('学習セッションIDが不正です。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?',
                             (registry_scope, 'sessions')).fetchone()
            sessions = json.loads(row[0]) if row else []
            if not isinstance(sessions, list) or any(not isinstance(value, str) or not value for value in sessions):
                raise ValueError('保存済みセッション一覧が不正です。元データを保持して停止しました。')
            sessions = list(dict.fromkeys([*sessions, session_id]))
            self._write(db, registry_scope, 'sessions', sessions)
            return sessions

    @staticmethod
    def _receipt(db: sqlite3.Connection, job_id: str, scope: str) -> bool:
        row = db.execute('SELECT scope FROM learning_receipts WHERE job_id=?', (job_id,)).fetchone()
        if row and row[0] != scope:
            raise ValueError('結果の科目・セッションが一致しません。')
        return row is not None

    def has_receipt(self, job_id: str, scope: str) -> bool:
        with self.connect() as db:
            return self._receipt(db, job_id, scope)

    def apply_result(self, job_id: str, scope: str, updates: dict, *, message_pair: list[dict] | None = None) -> bool:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._receipt(db, job_id, scope):
                return False
            if 'practice_set' in updates:
                # Archive the actual latest set, not a stale browser snapshot.
                # Archive, replacement and receipt must commit or roll back together.
                row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?',
                                 (scope, 'practice_set')).fetchone()
                previous = json.loads(row[0]) if row else None
                if previous is not None and not isinstance(previous, dict):
                    raise ValueError('保存済み練習の形式が不正です。元データを保持して停止しました。')
                if previous and previous.get('practice_id') != updates['practice_set']['practice_id']:
                    previous_id = previous.get('practice_id')
                    if not isinstance(previous_id, str) or not previous_id:
                        raise ValueError('保存済み練習のIDが不正です。元データを保持して停止しました。')
                    row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?',
                                     (scope, 'practice_ids')).fetchone()
                    ids = json.loads(row[0]) if row else []
                    if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
                        raise ValueError('練習履歴の形式が不正です。元データを保持して停止しました。')
                    self._write(db, scope, 'practice_archive:' + previous_id, previous)
                    self._write(db, scope, 'practice_ids', list(dict.fromkeys([*ids, previous_id])))
            if message_pair:
                row = db.execute('SELECT value FROM learning_documents WHERE scope=? AND name=?', (scope, 'history')).fetchone()
                updates = {**updates, 'history': (json.loads(row[0]) if row else []) + message_pair}
            for name, value in updates.items():
                self._write(db, scope, name, value)
            db.execute('INSERT INTO learning_receipts VALUES (?,?,?)', (job_id, scope, datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()))
            return True

    def list_scopes(self, prefix: str) -> list[str]:
        with self.connect() as db:
            rows = db.execute('SELECT DISTINCT scope FROM learning_documents ORDER BY scope').fetchall()
        return [r[0] for r in rows if r[0].startswith(prefix)]
