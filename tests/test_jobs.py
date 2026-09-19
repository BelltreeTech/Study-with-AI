"""Synthetic jobs, including independent processes; no Codex or real learner data."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.jobs import TERMINAL_STATES, JobManager


def wait_job(manager, job_id, expected=None, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job and (job["state"] == expected if expected else job["state"] in TERMINAL_STATES):
            return job
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {expected or 'terminal'}: {manager.get(job_id)['state']}")


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "jobs.sqlite3"
        self.managers = []

    def manager(self):
        result = JobManager(self.db, poll_interval=0.01)
        self.managers.append(result)
        return result

    def tearDown(self):
        for manager in self.managers:
            manager.shutdown()
        self.tmp.cleanup()

    def test_success_dedupes_rerun_and_intentional_attempt_is_new(self):
        manager = self.manager()
        calls = []
        def worker(cancel):
            calls.append(1)
            return {"answer": "synthetic"}
        first = manager.submit("answer", {"subject": "a", "session": "b"}, {"revision": "v1"}, "rerun-1", worker)
        again = manager.submit("answer", {"subject": "a", "session": "b"}, {"revision": "v1"}, "rerun-1", worker)
        self.assertEqual(first, again)
        self.assertEqual(wait_job(manager, first)["result"], {"answer": "synthetic"})
        second = manager.submit("answer", {"subject": "a", "session": "b"}, {"revision": "v1"}, "attempt-2", worker)
        self.assertNotEqual(first, second)
        wait_job(manager, second)
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ValueError):
            manager.submit("answer", {"subject": "different"}, {"revision": "v1"}, "rerun-1", worker)
        with self.assertRaises(ValueError):
            manager.submit("answer", {"subject": "a", "session": "b"}, {"revision": "changed"}, "rerun-1", worker)

    def test_multiple_managers_have_global_concurrency_one(self):
        first, second = self.manager(), self.manager()
        mutex = threading.Lock()
        counts = {"active": 0, "max": 0}
        def worker(cancel):
            with mutex:
                counts["active"] += 1
                counts["max"] = max(counts["max"], counts["active"])
            time.sleep(0.06)
            with mutex:
                counts["active"] -= 1
            return {"ok": True}
        jobs = [(manager, manager.submit("answer", "s", {}, f"unique-{i}", worker)) for i, manager in enumerate([first, second] * 3)]
        for manager, job_id in jobs:
            self.assertEqual(wait_job(manager, job_id)["state"], "succeeded")
        self.assertEqual(counts["max"], 1)

    def test_cross_process_global_concurrency(self):
        activity = Path(self.tmp.name) / "activity.sqlite3"
        with sqlite3.connect(activity) as conn:
            conn.execute("CREATE TABLE counter(active INTEGER, max_active INTEGER)")
            conn.execute("INSERT INTO counter VALUES (0,0)")
        script = '''
import sqlite3, sys, time
from src.jobs import JobManager, TERMINAL_STATES
m=JobManager(sys.argv[1], poll_interval=.01)
def worker(cancel):
    with sqlite3.connect(sys.argv[2]) as c:
        c.execute("UPDATE counter SET active=active+1")
        c.execute("UPDATE counter SET max_active=MAX(max_active,active)")
    time.sleep(.15)
    with sqlite3.connect(sys.argv[2]) as c: c.execute("UPDATE counter SET active=active-1")
    return {"ok":True}
j=m.submit("answer","s",{},sys.argv[3],worker)
while m.get(j)["state"] not in TERMINAL_STATES: time.sleep(.01)
assert m.get(j)["state"]=="succeeded"
m.shutdown()
'''
        children = [subprocess.Popen([sys.executable, "-c", script, str(self.db), str(activity), f"process-{i}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
        try:
            for child in children:
                stdout, stderr = child.communicate(timeout=12)
                self.assertEqual(child.returncode, 0, stderr.decode())
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                if child.stdout:
                    child.stdout.close()
                if child.stderr:
                    child.stderr.close()
        with sqlite3.connect(activity) as conn:
            self.assertEqual(conn.execute("SELECT active,max_active FROM counter").fetchone(), (0, 1))

    def test_cancel_running_from_other_manager_discards_late_result(self):
        first, second = self.manager(), self.manager()
        started = threading.Event()
        def worker(cancel):
            started.set()
            cancel.wait(3)
            return {"score": 100}
        job_id = first.submit("grade", "s", {}, "cancel", worker)
        self.assertTrue(started.wait(3))
        self.assertTrue(second.cancel(job_id))
        job = wait_job(first, job_id)
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNone(job["result"])
        self.assertFalse(second.cancel(job_id))

    def test_cancel_queued_never_calls_worker(self):
        manager = self.manager()
        started, release = threading.Event(), threading.Event()
        def blocker(cancel):
            started.set()
            release.wait(3)
            return {}
        first = manager.submit("answer", "s", {}, "blocker", blocker)
        self.assertTrue(started.wait(3))
        calls = []
        second = manager.submit("answer", "s", {}, "queued", lambda event: calls.append(1) or {})
        self.assertTrue(manager.cancel(second))
        release.set()
        wait_job(manager, first)
        self.assertEqual(wait_job(manager, second)["state"], "cancelled")
        self.assertEqual(calls, [])

    def test_rate_limit_failure_is_safe_and_not_retried(self):
        manager = self.manager()
        calls = []
        class Failure(Exception):
            code = "rate_limited"
        def worker(cancel):
            calls.append(1)
            raise Failure("PRIVATE ANSWER MUST NOT LEAK")
        job = wait_job(manager, manager.submit("answer", "s", {}, "failure", worker))
        self.assertEqual(job["state"], "failed")
        self.assertEqual(job["error_code"], "rate_limited")
        self.assertNotIn("PRIVATE", job["error_message"])
        self.assertEqual(calls, [1])

    def test_shutdown_waits_for_worker_cleanup_and_rejects_late_score(self):
        manager = self.manager()
        started, reaped = threading.Event(), threading.Event()
        def worker(cancel):
            started.set()
            cancel.wait(3)
            time.sleep(.04)
            reaped.set()
            return {"score": 100}
        job_id = manager.submit("grade", "s", {}, "shutdown", worker)
        self.assertTrue(started.wait(3))
        manager.shutdown()
        self.assertTrue(reaped.is_set())
        self.assertEqual(manager.get(job_id)["state"], "cancelled")
        self.assertIsNone(manager.get(job_id)["result"])
        with self.assertRaises(RuntimeError):
            manager.submit("a", "s", {}, "after-stop", lambda e: {})

    def test_recover_running_and_dead_owner_queue_as_interrupted(self):
        first = self.manager()
        job_id = first.submit("answer", "s", {}, "recover", lambda e: {})
        wait_job(first, job_id)
        first.shutdown()
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE jobs SET state='running',result=NULL,finished_at=NULL,owner_pid=2147483647 WHERE id=?", (job_id,))
        second = self.manager()
        self.assertEqual(second.get(job_id)["state"], "interrupted")
        second.shutdown()
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE jobs SET state='queued',finished_at=NULL,owner_pid=2147483647 WHERE id=?", (job_id,))
        third = self.manager()
        self.assertEqual(third.get(job_id)["state"], "interrupted")

    def test_diagnostics_exclude_payload_and_result(self):
        manager = self.manager()
        job_id = manager.submit("answer", "scope-a", {"private": "synthetic"}, "diagnostics", lambda e: {"answer": "synthetic"})
        wait_job(manager, job_id)
        listed = manager.list_jobs(scope="scope-a")
        self.assertEqual(len(listed), 1)
        self.assertNotIn("payload", listed[0])
        self.assertNotIn("result", listed[0])
        self.assertEqual(manager.list_jobs(scope="scope-b"), [])

    def test_crashed_parent_retains_lock_until_inherited_child_exits(self):
        marker = Path(self.tmp.name) / "synthetic-child-finished"
        script = r'''
import os, subprocess, sys, threading
from src.jobs import JobManager
m=JobManager(sys.argv[1],poll_interval=.01)
started=threading.Event()
def worker(cancel):
    child=subprocess.Popen([sys.executable,"-c","import pathlib,sys,time;time.sleep(.6);pathlib.Path(sys.argv[1]).write_text('finished')",sys.argv[2]],pass_fds=(cancel.execution_lock_fd,),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    started.set()
    child.wait()
    return {}
j=m.submit("answer","s",{},"crashed-parent",worker)
assert started.wait(3)
os._exit(0)
'''
        parent = subprocess.Popen([sys.executable, "-c", script, str(self.db), str(marker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _, stderr = parent.communicate(timeout=5)
            self.assertEqual(parent.returncode, 0, stderr.decode())
            self.assertFalse(marker.exists())
            manager = self.manager()
            def worker(cancel):
                return {"prior_child_exited": marker.exists()}
            job_id = manager.submit("answer", "s", {}, "after-crash", worker)
            time.sleep(.08)
            self.assertEqual(manager.get(job_id)["state"], "queued")
            result = wait_job(manager, job_id)
            self.assertEqual(result["result"], {"prior_child_exited": True})
            interrupted = [row for row in manager.list_jobs() if row["id"] != job_id]
            self.assertEqual(interrupted[0]["state"], "interrupted")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.communicate()

    def test_execution_lock_fd_is_available_to_provider(self):
        manager = self.manager()
        def worker(cancel):
            self.assertGreaterEqual(cancel.execution_lock_fd, 0)
            os.fstat(cancel.execution_lock_fd)
            return {"fd_available": True}
        job = wait_job(manager, manager.submit("answer", "s", {}, "fd", worker))
        self.assertEqual(job["result"], {"fd_available": True})


if __name__ == "__main__":
    unittest.main()
