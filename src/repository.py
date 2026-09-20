"""Transactional, versioned local persistence; never repairs corrupt data by erasing it."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
TOKYO = ZoneInfo("Asia/Tokyo")
T = TypeVar("T")


def ensure_private_database_file(db_path: Path) -> None:
    """Create with 0600 before SQLite creates WAL/SHM using the database mode."""
    try:
        fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    os.close(fd)


@contextmanager
def sqlite_initialization_lock(db_path: Path):
    """Serialize initial WAL/schema setup before SQLite's busy handler is usable."""
    fd = os.open(db_path.with_suffix(db_path.suffix + ".init.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class RepositoryError(RuntimeError):
    """Persistence is unavailable. The caller must not treat this as empty progress."""


def now_iso() -> str:
    return datetime.now(TOKYO).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def migrate_legacy_data(original: dict) -> dict:
    """Keep all original fields, including unrecognized top-level and course fields."""
    data = json.loads(canonical_json(original))
    if "courses" not in data:
        topic = data.get("topic") or "Default Course"
        if not isinstance(topic, str):
            raise RepositoryError("旧進捗のコース名が不正です。元JSONを保持して移行を停止しました。")
        course = {k: v for k, v in data.items() if k != "user_profile"}
        course.setdefault("curriculum", [])
        course.setdefault("current_chapter_index", 0)
        data["courses"] = {topic: course}
        data["last_active_course"] = topic
    if not isinstance(data["courses"], dict) or any(not isinstance(v, dict) for v in data["courses"].values()):
        raise RepositoryError("進捗のcourses形式が不正です。元データを保持して停止しました。")
    if "user_profile" in data and not isinstance(data["user_profile"], dict):
        raise RepositoryError("進捗のuser_profile形式が不正です。元データを保持して停止しました。")
    data.setdefault("last_active_course", "")
    return data


class Repository:
    """A JSON document in SQLite preserves unknown fields; updates use BEGIN IMMEDIATE.

    Only the first initialization imports legacy JSON. Its original bytes remain on
    disk and an exact text copy and SHA-256 are retained in migration_sources.
    No test or implicit repair ever accesses a different data directory.
    """

    def __init__(self, db_path: str | Path, legacy_json: str | Path | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.legacy_json = Path(legacy_json) if legacy_json is not None else self.db_path.parent / "progress.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        try:
            ensure_private_database_file(self.db_path)
            conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        except sqlite3.Error as exc:
            raise RepositoryError("進捗データベースを開けません。バックアップを確認してください。") from exc

    def _initialize(self) -> None:
        with sqlite_initialization_lock(self.db_path):
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        conn = self._connect()
        try:
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS repository_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM repository_meta WHERE key='schema_version'").fetchone()
            if row is not None and int(row[0]) != SCHEMA_VERSION:
                raise RepositoryError("この進捗DBのバージョンには未対応です。更新を停止しました。")
            conn.execute("CREATE TABLE IF NOT EXISTS progress_state (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT NOT NULL, updated_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS progress_events (event_id TEXT PRIMARY KEY, fingerprint TEXT, result TEXT NOT NULL, created_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS migration_sources (source_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, sha256 TEXT NOT NULL, original_json TEXT NOT NULL, migrated_at TEXT NOT NULL)")
            state = conn.execute("SELECT document FROM progress_state WHERE id=1").fetchone()
            if state is None and row is not None:
                raise RepositoryError("保存済み進捗が欠落しています。空データへの置換を停止しました。")
            if state is None:
                data: dict = {"courses": {}, "last_active_course": ""}
                if self.legacy_json.exists():
                    try:
                        raw_bytes = self.legacy_json.read_bytes()
                        raw = raw_bytes.decode("utf-8")
                        original = json.loads(raw)
                        if not isinstance(original, dict):
                            raise ValueError("Expected a JSON object")
                        data = migrate_legacy_data(original)
                    except (OSError, UnicodeError, ValueError) as exc:
                        raise RepositoryError("旧progress.jsonを読み込めません。元JSONを保持し、空データへの置換と移行を停止しました。") from exc
                    conn.execute("INSERT INTO migration_sources VALUES ('legacy_progress_json',?,?,?,?)", (str(self.legacy_json.resolve()), hashlib.sha256(raw_bytes).hexdigest(), raw, now_iso()))
                conn.execute("INSERT INTO progress_state VALUES (1,?,?)", (canonical_json(data), now_iso()))
            else:
                self._decode(state[0])
            conn.execute("INSERT OR IGNORE INTO repository_meta VALUES ('schema_version',?)", (str(SCHEMA_VERSION),))
            conn.commit()
            os.chmod(self.db_path, 0o600)
        except (sqlite3.Error, ValueError) as exc:
            conn.rollback()
            raise RepositoryError("進捗DBが破損しているか読み込めません。空データへの置換は行いません。") from exc
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _decode(raw: str) -> dict:
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get("courses"), dict):
                raise ValueError("Invalid progress schema")
            return value
        except (ValueError, TypeError) as exc:
            raise RepositoryError("保存済み進捗が破損しています。書き換えを停止しました。") from exc

    def read(self) -> dict:
        conn = self._connect()
        try:
            row = conn.execute("SELECT document FROM progress_state WHERE id=1").fetchone()
            if row is None:
                raise RepositoryError("保存済み進捗が欠落しています。書き換えを停止しました。")
            return self._decode(row[0])
        except sqlite3.Error as exc:
            raise RepositoryError("進捗の読み込みに失敗しました。") from exc
        finally:
            conn.close()

    def update(self, mutation: Callable[[dict], T], *, event_id: str | None = None, fingerprint: str | None = None) -> tuple[bool, T]:
        """Apply atomically, returning (new_event, result). Duplicate events reuse result."""
        if event_id == "":
            raise ValueError("event_id must not be empty")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if event_id is not None:
                prior = conn.execute("SELECT fingerprint,result FROM progress_events WHERE event_id=?", (event_id,)).fetchone()
                if prior is not None:
                    if prior[0] != fingerprint:
                        raise ValueError("同じイベントIDに異なる内容は保存できません。")
                    conn.commit()
                    return False, json.loads(prior[1])
            row = conn.execute("SELECT document FROM progress_state WHERE id=1").fetchone()
            if row is None:
                raise RepositoryError("保存済み進捗が欠落しています。書き換えを停止しました。")
            data = self._decode(row[0])
            result = mutation(data)
            serialized = canonical_json(data)
            self._decode(serialized)
            conn.execute("UPDATE progress_state SET document=?,updated_at=? WHERE id=1", (serialized, now_iso()))
            if event_id is not None:
                conn.execute("INSERT INTO progress_events VALUES (?,?,?,?)", (event_id, fingerprint, canonical_json(result), now_iso()))
            conn.commit()
            return True, result
        except sqlite3.Error as exc:
            conn.rollback()
            raise RepositoryError("進捗の保存に失敗しました。変更を取り消しました。") from exc
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migration_info(self) -> list[dict]:
        """Metadata only; no learner content is returned to diagnostics."""
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute("SELECT source_id,sha256,migrated_at FROM migration_sources")]
        finally:
            conn.close()

    def backup(self, destination: str | Path) -> Path:
        """Use SQLite's online backup API so WAL contents are included consistently."""
        destination = Path(destination).expanduser().resolve()
        if destination.exists():
            raise FileExistsError("バックアップ先が既に存在します。別名を指定してください。")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        source = self._connect()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination
