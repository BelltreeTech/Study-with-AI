"""SQLite jobs with one active generation across local processes and browser tabs.

The worker receives a cooperative cancellation Event. Only the Provider owns and
terminates its child process group. An OS file lock is held until the worker has
actually returned, including during cancellation; no timeout can release it early.
"""
from __future__ import annotations

import atexit
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from src.output_contract import diagnostic_message, sanitize_diagnostic
from src.repository import canonical_json, ensure_private_database_file, now_iso, sqlite_initialization_lock

TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
Worker = Callable[[threading.Event], dict]
ERROR_MESSAGES = {
    "auth_required": "CodexのChatGPTログインが必要です。",
    "authentication": "CodexのChatGPTログインを確認してください。",
    "model_unavailable": "指定したGPT-6モデルを利用できません。",
    "model_unconfirmed": "指定モデルの一覧情報が未確認です。管理用の小さな検証を先に実行してください。",
    "rate_limit": "Codexの利用枠に達しました。利用可能になるまで待ってください。",
    "quota_exhausted": "Codexの利用枠に達しました。利用可能になるまで待ってください。",
    "timeout": "生成が制限時間を超えたため停止しました。",
    "cancelled": "生成をキャンセルしました。",
    "network_error": "Codexとの通信に失敗しました。",
    "schema_error": "生成結果の形式が不正です。進捗は更新していません。",
    "schema_unsupported": "Codexが出力形式の設定を拒否しました。アプリのschema互換性を確認してください。",
    "invalid_output": "生成結果を検証できません。進捗は更新していません。",
    "output_limit": "生成出力が上限を超えたため停止しました。",
    "cli_not_found": "公式Codex CLIが見つかりません。",
    "startup_failed": "Codexを起動できません。診断画面を確認してください。",
    "nonzero_exit": "Codexがエラー終了しました。",
    "incomplete_output": "Codexの応答が途中で切れました。",
    "rate_limited": "Codexの利用枠に達しました。利用可能になるまで待ってください。",
    "process_error": "Codexがエラー終了しました。",
    "invalid_request": "生成要求を検証できません。入力と設定を確認してください。",
    "invalid_result": "生成結果の内容に矛盾があります。進捗は更新していません。",
    "boundary_unavailable": "Codexの安全な実行境界を確認できないため、生成を停止しました。",
    "tool_violation": "不要なツール呼び出しが検出されたため、生成を停止しました。",
    "worker_error": "生成処理に失敗しました。進捗は更新していません。",
}


class JobManager:
    """Jobs persist, but callable workers deliberately do not survive a restart.

    A recovered unfinished request becomes interrupted, never silently rerun.
    Keep the manager as a process resource (e.g. st.cache_resource), not per rerun.
    No automatic retry consumes the user's quota. A user retry uses a new key.
    """

    def __init__(self, db_path: str | Path, *, poll_interval: float = 0.05):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.db_path.with_suffix(self.db_path.suffix + ".generation.lock")
        self.owner = uuid.uuid4().hex
        self.pid = os.getpid()
        self.poll_interval = max(0.01, poll_interval)
        self._workers: dict[str, Worker] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._mutex = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._initialize()
        self._recover_if_unlocked()
        self._thread = threading.Thread(target=self._run_loop, name=f"study-jobs-{self.owner[:8]}", daemon=True)
        self._thread.start()
        atexit.register(self.shutdown)

    def _connect(self) -> sqlite3.Connection:
        ensure_private_database_file(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _initialize(self) -> None:
        with sqlite_initialization_lock(self.db_path):
            self._initialize_locked()

    def _initialize_locked(self) -> None:
        with closing(self._connect()) as conn:
            if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("CREATE TABLE IF NOT EXISTS jobs_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM jobs_meta WHERE key='schema_version'").fetchone()
            if row is not None and row[0] != "1":
                raise RuntimeError("未対応のジョブDBバージョンです。")
            conn.execute("INSERT OR IGNORE INTO jobs_meta VALUES ('schema_version','1')")
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL,
                payload TEXT NOT NULL, idempotency_key TEXT UNIQUE NOT NULL,
                request_digest TEXT NOT NULL, state TEXT NOT NULL,
                owner TEXT NOT NULL, owner_pid INTEGER NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                result TEXT, error_code TEXT, error_message TEXT,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                CHECK(state IN ('queued','running','succeeded','failed','cancelled','interrupted'))
            )""")
            conn.execute("CREATE TABLE IF NOT EXISTS job_diagnostics (job_id TEXT PRIMARY KEY, diagnostic TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_state_owner ON jobs(state,owner)")
        os.chmod(self.db_path, 0o600)

    def submit(self, kind: str, scope: str | dict, payload: dict, idempotency_key: str, worker: Worker) -> str:
        if not kind or not idempotency_key or not callable(worker):
            raise ValueError("kind, idempotency_key and worker are required")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        request = canonical_json([kind, scope, payload])
        digest = hashlib.sha256(request.encode()).hexdigest()
        job_id = uuid.uuid4().hex
        with self._mutex:
            if self._stop.is_set():
                raise RuntimeError("JobManagerは停止済みです。")
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                prior = conn.execute("SELECT id,request_digest FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if prior is not None:
                    if prior[1] != digest:
                        raise ValueError("同じリクエストIDに異なる科目・入力は指定できません。")
                    conn.commit()
                    return str(prior[0])
                conn.execute("INSERT INTO jobs (id,kind,scope,payload,idempotency_key,request_digest,state,owner,owner_pid,created_at) VALUES (?,?,?,?,?,?,'queued',?,?,?)", (job_id, kind, canonical_json(scope), canonical_json(payload), idempotency_key, digest, self.owner, self.pid, now_iso()))
                self._workers[job_id] = worker
                self._cancel_events[job_id] = threading.Event()
                conn.commit()
            except BaseException:
                conn.rollback()
                self._workers.pop(job_id, None)
                self._cancel_events.pop(job_id, None)
                raise
            finally:
                conn.close()
        self._wake.set()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            diagnostic = conn.execute("SELECT diagnostic FROM job_diagnostics WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["diagnostic"] = sanitize_diagnostic(json.loads(diagnostic[0])) if diagnostic else {}
        for key in ("scope", "payload", "result"):
            value[key] = json.loads(value[key]) if value[key] is not None else None
        value["job_id"] = value["id"]
        value["cancel_requested"] = bool(value["cancel_requested"])
        return value

    def list_jobs(self, *, scope: str | dict | None = None, limit: int = 50) -> list[dict]:
        """Return metadata for diagnostics. Raw prompt/payload/result are excluded."""
        limit = max(1, min(limit, 200))
        columns = "id,kind,state,cancel_requested,error_code,error_message,created_at,started_at,finished_at"
        with closing(self._connect()) as conn:
            if scope is None:
                rows = conn.execute(f"SELECT {columns} FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
            else:
                rows = conn.execute(f"SELECT {columns} FROM jobs WHERE scope=? ORDER BY created_at DESC LIMIT ?", (canonical_json(scope), limit))
            return [dict(row) for row in rows]

    def cancel(self, job_id: str) -> bool:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row[0] in TERMINAL_STATES:
                conn.commit()
                return False
            if row[0] == "queued":
                conn.execute("UPDATE jobs SET state='cancelled',cancel_requested=1,finished_at=?,error_code='cancelled',error_message=? WHERE id=?", (now_iso(), ERROR_MESSAGES["cancelled"], job_id))
            else:
                conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
            conn.commit()
        finally:
            conn.close()
        with self._mutex:
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()
        self._wake.set()
        return True

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _execution_lock(self) -> int | None:
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            os.close(fd)
            return None

    def _recover(self, conn: sqlite3.Connection) -> None:
        """Caller holds the OS execution lock: any running row is now orphaned."""
        conn.execute("UPDATE jobs SET state='interrupted',finished_at=?,error_code='interrupted',error_message=? WHERE state='running'", (now_iso(), "前回の生成が中断しました。再実行には新しいリクエストが必要です。"))
        owners = conn.execute("SELECT DISTINCT owner_pid FROM jobs WHERE state='queued'").fetchall()
        for row in owners:
            if not self._pid_alive(row[0]):
                conn.execute("UPDATE jobs SET state='interrupted',finished_at=?,error_code='interrupted',error_message=? WHERE state='queued' AND owner_pid=?", (now_iso(), "アプリが終了したため未実行の要求を中断しました。", row[0]))

    def _recover_if_unlocked(self) -> None:
        fd = self._execution_lock()
        if fd is None:
            return
        try:
            with closing(self._connect()) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._recover(conn)
                conn.commit()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.poll_interval)
            self._wake.clear()
            fd = self._execution_lock()
            if fd is None:
                continue
            try:
                conn = self._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    self._recover(conn)
                    row = conn.execute("SELECT id FROM jobs WHERE owner=? AND state='queued' ORDER BY created_at LIMIT 1", (self.owner,)).fetchone()
                    if row is None or self._stop.is_set():
                        conn.commit()
                        continue
                    job_id = str(row[0])
                    conn.execute("UPDATE jobs SET state='running',started_at=? WHERE id=? AND state='queued'", (now_iso(), job_id))
                    conn.commit()
                finally:
                    conn.close()
                self._execute(job_id, fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _execute(self, job_id: str, execution_lock_fd: int) -> None:
        with self._mutex:
            worker = self._workers[job_id]
            cancelled = self._cancel_events[job_id]
            # The Provider inherits this fd in its own child so a killed parent
            # cannot release the generation lock while Codex is still running.
            cancelled.execution_lock_fd = execution_lock_fd  # type: ignore[attr-defined]
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                result = worker(cancelled)
                if not isinstance(result, dict):
                    raise ValueError("Worker must return a validated dictionary")
                outcome["result"] = canonical_json(result)
            except BaseException as exc:
                code = str(getattr(exc, "code", "worker_error"))
                outcome["diagnostic"] = sanitize_diagnostic(getattr(exc, "diagnostic", None))
                outcome["error_code"] = code if re.fullmatch(r"[a-z_]{1,48}", code) else "worker_error"
            finally:
                completed.set()

        thread = threading.Thread(target=invoke, name=f"study-worker-{job_id[:8]}", daemon=True)
        thread.start()
        while not completed.wait(self.poll_interval):
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if self._stop.is_set() or (row and row[0]):
                cancelled.set()
        thread.join()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state,cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row and row[0] == "running":
                if row[1] or cancelled.is_set():
                    state, result, code = "cancelled", None, "cancelled"
                elif "error_code" in outcome:
                    state, result, code = "failed", None, outcome["error_code"]
                else:
                    state, result, code = "succeeded", outcome["result"], None
                message = ERROR_MESSAGES.get(code, ERROR_MESSAGES["worker_error"]) if code else None
                if state == "failed" and code == "schema_error" and outcome.get("diagnostic"):
                    detail = outcome["diagnostic"]
                    conn.execute("INSERT OR REPLACE INTO job_diagnostics VALUES (?,?)", (job_id, canonical_json(detail)))
                    message = diagnostic_message(detail) + " 進捗は更新していません。自動再生成は行いません。"
                conn.execute("UPDATE jobs SET state=?,result=?,error_code=?,error_message=?,finished_at=? WHERE id=?", (state, result, code, message, now_iso(), job_id))
            conn.commit()
        finally:
            conn.close()
            with self._mutex:
                self._workers.pop(job_id, None)
                self._cancel_events.pop(job_id, None)

    def shutdown(self, wait: bool = True) -> None:
        """Stop only this manager's jobs; wait for Provider process reaping by default."""
        with self._mutex:
            self._stop.set()
            for event in self._cancel_events.values():
                event.set()
        with closing(self._connect()) as conn:
            conn.execute("UPDATE jobs SET state='interrupted',finished_at=?,error_code='interrupted',error_message=? WHERE owner=? AND state='queued'", (now_iso(), "アプリ終了により未実行の要求を中断しました。", self.owner))
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE owner=? AND state='running'", (self.owner,))
        self._wake.set()
        if wait and self._thread is not threading.current_thread():
            self._thread.join()
        atexit.unregister(self.shutdown)

    def __enter__(self) -> JobManager:
        return self

    def __exit__(self, *_: Any) -> None:
        self.shutdown()
