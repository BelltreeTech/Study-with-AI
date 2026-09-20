"""Synthetic-only persistence regression tests; never load repository user_data."""
import datetime
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from src import progress
from src.repository import Repository, RepositoryError


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.db = self.path / "progress.sqlite3"
        self.legacy = self.path / "progress.json"
        self.patches = [patch.object(progress, "k_progressDir", self.path), patch.object(progress, "k_progressFile", self.legacy)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def fixture(self):
        data = {"courses": {"合成教材": {"curriculum": [{"title": "一章"}], "current_chapter_index": 0, "exp": 7, "weaknesses": {"合成語": {"srs_level": 1, "next_review": "2020-01-01"}}, "unknown_course": {"keep": True}}, "集中学習": {"curriculum": []}}, "last_active_course": "合成教材", "user_profile": {"total_exp": 7, "unknown_profile": [1, 2]}, "unknown_root": {"keep": "fixture"}}
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        self.legacy.write_text(raw, encoding="utf-8")
        return data, raw

    def test_migration_preserves_unknown_fields_and_original_bytes(self):
        data, raw = self.fixture()
        repo = Repository(self.db)
        self.assertEqual(repo.read(), data)
        self.assertEqual(self.legacy.read_text(encoding="utf-8"), raw)
        self.assertEqual(len(repo.migration_info()), 1)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)

    def test_migration_is_idempotent_and_does_not_replace_new_data(self):
        self.fixture()
        progress.add_exp("合成教材", 11, event_id="synthetic-xp")
        self.legacy.write_text('{"courses":{},"other":"changed legacy"}')
        self.assertEqual(Repository(self.db).read()["user_profile"]["total_exp"], 18)
        self.assertEqual(len(Repository(self.db).migration_info()), 1)

    def test_old_single_course_schema_keeps_unknown_fields(self):
        original = {"topic": "旧合成科目", "curriculum": [{"id": 1}], "current_chapter_index": 1, "unknown": [1, 2], "user_profile": {"total_exp": 13}}
        self.legacy.write_text(json.dumps(original))
        data = Repository(self.db).read()
        self.assertEqual(data["courses"]["旧合成科目"]["unknown"], [1, 2])
        self.assertEqual(data["unknown"], [1, 2])
        self.assertEqual(data["user_profile"]["total_exp"], 13)

    def test_corrupt_json_is_never_replaced_by_empty_progress(self):
        raw = b'{"courses": broken'
        self.legacy.write_bytes(raw)
        with self.assertRaises(RepositoryError):
            progress.add_exp("test", 10)
        self.assertEqual(self.legacy.read_bytes(), raw)

    def test_corrupt_sqlite_is_never_reset(self):
        raw = b"not a sqlite database"
        self.db.write_bytes(raw)
        with self.assertRaises(RepositoryError):
            Repository(self.db)
        self.assertEqual(self.db.read_bytes(), raw)

    def test_corrupt_saved_document_fails_closed(self):
        repo = Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE progress_state SET document='broken'")
        with self.assertRaises(RepositoryError):
            repo.update(lambda data: data.update(new=True))
        with self.assertRaises(RepositoryError):
            Repository(self.db)

    def test_missing_state_row_in_initialized_db_fails_closed(self):
        Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM progress_state")
        with self.assertRaises(RepositoryError):
            Repository(self.db)

    def test_future_schema_fails_closed(self):
        Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE repository_meta SET value='999' WHERE key='schema_version'")
        with self.assertRaises(RepositoryError):
            Repository(self.db)

    def test_course_update_preserves_grades_weaknesses_exp_unknown(self):
        self.fixture()
        progress.save_course_progress("合成教材", [{"title": "更新"}], 1, metadata={"subject": "category/subject"})
        course = progress.load_course_progress("合成教材")
        self.assertEqual(course["exp"], 7)
        self.assertEqual(course["unknown_course"], {"keep": True})
        self.assertIn("合成語", course["weaknesses"])
        self.assertEqual(course["subject"], "category/subject")
        self.assertIn("集中学習", progress.get_all_courses())

    def test_concurrent_unique_xp_and_duplicate_event_are_atomic(self):
        Repository(self.db)
        def award(i):
            progress.add_exp("synthetic", 1, event_id=f"award-{i % 20}")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(award, range(80)))
        data = progress.get_dashboard_data()
        self.assertEqual(data["profile"]["total_exp"], 20)
        self.assertEqual(data["courses"]["synthetic"]["exp"], 20)

    def test_learning_completion_atomic_and_exactly_once(self):
        arguments = {"exp_amount": 50, "weaknesses": ["synthetic"], "grading_result": {"score": 80}, "curriculum": [{"status": "completed"}], "current_chapter_index": 1}
        self.assertTrue(progress.commit_learning_event("synthetic", "attempt-1", **arguments))
        self.assertFalse(progress.commit_learning_event("synthetic", "attempt-1", **arguments))
        course = progress.load_course_progress("synthetic")
        self.assertEqual(course["exp"], 50)
        self.assertEqual(len(course["grade_history"]), 1)
        self.assertEqual(course["weaknesses"]["synthetic"]["error_count"], 1)
        with self.assertRaises(ValueError):
            progress.commit_learning_event("synthetic", "attempt-1", exp_amount=99)

    def test_transaction_rolls_back_all_updates_when_mutator_fails(self):
        repo = Repository(self.db)
        def invalid(data):
            data["new"] = "should roll back"
            raise ValueError("synthetic")
        with self.assertRaises(ValueError):
            repo.update(invalid, event_id="failed")
        self.assertNotIn("new", repo.read())
        self.assertTrue(repo.update(lambda data: data.update(ok=True), event_id="failed")[0])

    def test_pomodoro_combined_with_xp_is_one_event(self):
        args = {"exp_amount": 20, "pomodoro_minutes": 25}
        progress.commit_learning_event(None, "timer-1", **args)
        progress.commit_learning_event(None, "timer-1", **args)
        profile = progress.get_dashboard_data()["profile"]
        self.assertEqual((profile["total_pomodoros"], profile["focused_minutes"], profile["total_exp"]), (1, 25, 20))
        self.assertTrue(profile["last_pomodoro_at"].endswith("+09:00"))

    def test_review_clear_returns_status_and_is_idempotent(self):
        progress.update_weaknesses("s", ["term"], event_id="weakness-1")
        self.assertEqual(progress.process_weakness_clear("s", "term", event_id="review-1"), "leveled_up")
        self.assertEqual(progress.process_weakness_clear("s", "term", event_id="review-1"), "leveled_up")
        self.assertEqual(progress.get_weaknesses("s")["term"]["srs_level"], 2)
        progress.process_weakness_clear("s", "term", event_id="review-2")
        self.assertEqual(progress.process_weakness_clear("s", "term", event_id="review-3"), "mastered")

    def test_daily_exp_does_not_reuse_yesterdays_total(self):
        with patch.object(progress, "_today", return_value=datetime.date(2026, 1, 1)):
            progress.add_exp("s", 100, event_id="jan-1")
        with patch.object(progress, "_today", return_value=datetime.date(2026, 1, 2)):
            self.assertEqual(progress.get_dashboard_data()["profile"]["daily_exp"], 0)
            self.assertFalse(progress.check_and_update_streak(100))
            progress.add_exp("s", 100, event_id="jan-2")
            self.assertTrue(progress.check_and_update_streak(100))
            self.assertFalse(progress.check_and_update_streak(100))

    def test_online_backup_includes_latest_wal_and_is_independent(self):
        repo = Repository(self.db)
        repo.update(lambda data: data.update(synthetic=42))
        backup = self.path / "backup.sqlite3"
        repo.backup(backup)
        repo.update(lambda data: data.update(synthetic=43))
        self.assertEqual(Repository(backup).read()["synthetic"], 42)
        with self.assertRaises(FileExistsError):
            repo.backup(backup)


if __name__ == "__main__":
    unittest.main()
