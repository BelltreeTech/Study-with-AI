"""Synthetic concurrent tabs must not discard a newer exam or an active grade."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.learning_repository import LearningRepository

SCOPE = 'synthetic/session/exam'


def exam(attempt='old'):
    return {'attempt_id': attempt, 'title': 'Synthetic exam', 'questions': [
        {'id': 'q1', 'prompt': 'Explain recall.', 'max_points': 100,
         'model_answer': 'SECRET_REFERENCE', 'rubric': 'SECRET_RUBRIC'},
    ]}


@pytest.fixture
def stores(tmp_path):
    first = LearningRepository(tmp_path / 'learning.sqlite3')
    second = LearningRepository(first.path)
    first.set(SCOPE, 'quiz', exam())
    first.set(SCOPE, 'grade', {'attempt_id': 'old', 'score': 100})
    first.set(SCOPE, 'answer_draft:old', 'Synthetic original answer')
    return first, second


def test_reset_archives_only_public_questions_once_and_retains_original_draft(stores):
    store, _ = stores
    assert store.reset_exam(SCOPE, 'old', lambda _: False)
    assert not store.reset_exam(SCOPE, 'old', lambda _: False)
    assert store.get(SCOPE, 'quiz') is None and store.get(SCOPE, 'grade') is None
    archived = store.get(SCOPE, 'answer_archive')
    assert len(archived) == 1 and archived[0]['attempt_id'] == 'old'
    assert archived[0]['answer'] == store.get(SCOPE, 'answer_draft:old') == 'Synthetic original answer'
    assert 'SECRET_' not in json.dumps(archived)
    with store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1


def test_stale_reset_cannot_clear_newer_exam_or_grade(stores):
    old_tab, new_tab = stores
    assert new_tab.reset_exam(SCOPE, 'old', lambda _: False)
    newer = exam('newer')
    new_tab.apply_result('newer-job', SCOPE, {'quiz': newer, 'grade': {'attempt_id': 'newer', 'score': 84}})
    assert not old_tab.reset_exam(SCOPE, 'old', lambda _: False)
    assert old_tab.get(SCOPE, 'quiz') == newer
    assert old_tab.get(SCOPE, 'grade') == {'attempt_id': 'newer', 'score': 84}


def test_reset_lock_serializes_archive_and_clear_before_next_submission(stores):
    reset_tab, submit_tab = stores
    reset_tab.set(SCOPE, 'pending', 'previous-failed-job')
    checked, release, submission_started, registered = (threading.Event() for _ in range(4))

    def active(_):
        checked.set()
        assert release.wait(5)
        return False

    def submit():
        submission_started.set()

        def register():
            registered.set()
            return 'newer-job'

        claim = submit_tab.claim_submission(SCOPE, register, lambda _: False)
        submit_tab.apply_result('newer-job', SCOPE, {'quiz': exam('newer'), 'grade': None})
        return claim

    with ThreadPoolExecutor(max_workers=2) as executor:
        reset = executor.submit(reset_tab.reset_exam, SCOPE, 'old', active)
        assert checked.wait(3)
        submission = executor.submit(submit)
        try:
            assert submission_started.wait(3)
            assert not registered.wait(.1), 'A submission must not enter an in-progress reset transaction'
        finally:
            release.set()
        assert reset.result(timeout=3)
        assert submission.result(timeout=3) == ('newer-job', True)
    assert reset_tab.get(SCOPE, 'quiz')['attempt_id'] == 'newer'
    assert reset_tab.get(SCOPE, 'pending') == 'newer-job'
    assert len(reset_tab.get(SCOPE, 'answer_archive')) == 1


def test_grade_claim_winning_the_lock_prevents_reset(stores):
    grade_tab, reset_tab = stores
    claimed, release, resetting = (threading.Event() for _ in range(3))

    def register():
        claimed.set()
        assert release.wait(5)
        return 'active-grade'

    def reset():
        resetting.set()
        return reset_tab.reset_exam(SCOPE, 'old', lambda job_id: job_id == 'active-grade')

    with ThreadPoolExecutor(max_workers=2) as executor:
        grade = executor.submit(grade_tab.claim_submission, SCOPE, register, lambda _: False)
        assert claimed.wait(3)
        pending_reset = executor.submit(reset)
        try:
            assert resetting.wait(3)
            assert not pending_reset.done()
        finally:
            release.set()
        assert grade.result(timeout=3) == ('active-grade', True)
        assert pending_reset.result(timeout=3) is False
    assert reset_tab.get(SCOPE, 'quiz') == exam()
    assert reset_tab.get(SCOPE, 'grade') == {'attempt_id': 'old', 'score': 100}
    assert reset_tab.get(SCOPE, 'answer_draft:old') == 'Synthetic original answer'
    assert reset_tab.get(SCOPE, 'answer_archive') is None


def test_failed_reset_preserves_all_documents_and_existing_archive(stores, monkeypatch):
    store, _ = stores
    previous = [{'attempt_id': 'earlier', 'exam': {'title': 'Earlier', 'questions': []},
                 'answer': 'Earlier answer', 'unknown_metadata': {'keep': True}}]
    store.set(SCOPE, 'answer_archive', previous)
    original_write = store._write

    def fail_at_clear(db, scope, name, value):
        if name == 'quiz':
            raise RuntimeError('Synthetic failure after archive write')
        original_write(db, scope, name, value)

    monkeypatch.setattr(store, '_write', fail_at_clear)
    with pytest.raises(RuntimeError, match='Synthetic failure'):
        store.reset_exam(SCOPE, 'old', lambda _: False)
    assert store.get(SCOPE, 'quiz') == exam()
    assert store.get(SCOPE, 'grade') == {'attempt_id': 'old', 'score': 100}
    assert store.get(SCOPE, 'answer_archive') == previous
