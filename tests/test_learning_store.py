"""Synthetic local learning-store lifecycle, scope and multi-tab regressions."""
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from src.learning_repository import LearningRepository


def test_private_creation_and_wal_permissions(tmp_path, monkeypatch):
    path = tmp_path / 'private' / 'learning.sqlite3'
    original_connect = sqlite3.connect
    observed = []

    def verify_private_before_sqlite(*args, **kwargs):
        observed.append(path.stat().st_mode & 0o777)
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', verify_private_before_sqlite)
    repository = LearningRepository(path)
    assert observed and all(mode == 0o600 for mode in observed)
    with repository.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("INSERT INTO learning_documents VALUES ('test','synthetic','[]')")
        assert path.stat().st_mode & 0o777 == 0o600
        for sibling in (path.with_name(path.name + '-wal'), path.with_name(path.name + '-shm')):
            assert sibling.stat().st_mode & 0o777 == 0o600


def test_parallel_first_initialization_preserves_all_writes(tmp_path):
    path = tmp_path / 'learning.sqlite3'
    barrier = threading.Barrier(8)

    def initialize(index):
        barrier.wait(timeout=10)
        repository = LearningRepository(path)
        repository.set('scope', f'name-{index}', {'synthetic': index})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(initialize, range(8)))
    repository = LearningRepository(path)
    for index in range(8):
        assert repository.get('scope', f'name-{index}') == {'synthetic': index}


def test_future_version_is_not_downgraded(tmp_path):
    path = tmp_path / 'learning.sqlite3'
    repository = LearningRepository(path)
    repository.set('scope', 'synthetic', {'keep': True})
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(RuntimeError, match='バージョン'):
        LearningRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert json.loads(db.execute('SELECT value FROM learning_documents').fetchone()[0]) == {'keep': True}


def test_corrupt_database_and_missing_table_preserved(tmp_path):
    path = tmp_path / 'corrupt.sqlite3'
    original = b'not a database: synthetic content'
    path.write_bytes(original)
    with pytest.raises(RuntimeError):
        LearningRepository(path)
    assert path.read_bytes() == original
    path = tmp_path / 'missing.sqlite3'
    LearningRepository(path)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE learning_documents')
    with pytest.raises(RuntimeError, match='欠落'):
        LearningRepository(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='learning_documents'").fetchone() is None


def test_two_tabs_claim_same_scope_only_submits_once(tmp_path):
    path = tmp_path / 'learning.sqlite3'
    repositories = [LearningRepository(path), LearningRepository(path)]
    barrier = threading.Barrier(2)
    calls = []

    def run(tab):
        barrier.wait(timeout=10)

        def create_job():
            calls.append(tab)
            return f'job-from-tab-{tab}'

        return repositories[tab].claim_submission('subject/session', create_job, lambda _: True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, [0, 1]))
    assert len(calls) == 1
    assert result[0][0] == result[1][0]
    assert sorted(created for _, created in result) == [False, True]
    assert repositories[0].get('subject/session', 'pending') == result[0][0]


def test_claim_scope_isolation_active_policy_and_failure_rollback(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    assert repository.claim_submission('A', lambda: 'job-a', lambda _: True) == ('job-a', True)
    assert repository.claim_submission('B', lambda: 'job-b', lambda _: True) == ('job-b', True)
    skipped = Mock(side_effect=AssertionError('active submission should not run'))
    assert repository.claim_submission('A', skipped, lambda _: True) == ('job-a', False)
    skipped.assert_not_called()
    assert repository.claim_submission('A', lambda: 'retry-a', lambda _: False) == ('retry-a', True)
    with pytest.raises(ValueError, match='synthetic failure'):
        repository.claim_submission('A', Mock(side_effect=ValueError('synthetic failure')), lambda _: False)
    assert repository.get('A', 'pending') == 'retry-a'


def test_receipt_is_atomic_idempotent_and_scoped(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    assert not repository.has_receipt('job-1', 'subject/session')
    assert repository.apply_result('job-1', 'subject/session', {'answer': {'markdown': 'synthetic'}},
                                   message_pair=[{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'a'}])
    assert repository.has_receipt('job-1', 'subject/session')
    assert not repository.apply_result('job-1', 'subject/session', {'answer': 'ignored'}, message_pair=[{}])
    assert len(repository.get('subject/session', 'history')) == 2
    assert repository.get('subject/session', 'answer') == {'markdown': 'synthetic'}
    with pytest.raises(ValueError, match='一致'):
        repository.has_receipt('job-1', 'other/session')
    with pytest.raises(ValueError, match='一致'):
        repository.apply_result('job-1', 'other/session', {'answer': 'wrong'})
    assert repository.get('other/session', 'answer') is None


def test_apply_failure_rolls_back_documents_and_receipt(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    repository.set('scope', 'existing', 'preserved')
    with pytest.raises(ValueError):
        repository.apply_result('failed-job', 'scope', {'existing': 'changed', 'bad': float('nan')})
    assert repository.get('scope', 'existing') == 'preserved'
    assert not repository.has_receipt('failed-job', 'scope')


def test_concurrent_results_append_history_without_lost_messages(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')

    def apply(index):
        return repository.apply_result(f'job-{index}', 'scope', {}, message_pair=[{'synthetic': index}])

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(pool.map(apply, range(16)))
    assert sorted(item['synthetic'] for item in repository.get('scope', 'history')) == list(range(16))


def test_clear_pending_cannot_remove_a_newer_job_from_another_tab(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    repository.set('scope', 'pending', 'completed-job')
    observed_by_slow_tab = repository.get('scope', 'pending')
    assert repository.clear_pending('scope', 'completed-job')
    assert repository.claim_submission('scope', lambda: 'new-job', lambda _: False) == ('new-job', True)
    assert not repository.clear_pending('scope', observed_by_slow_tab)
    assert repository.get('scope', 'pending') == 'new-job'
    assert not repository.clear_pending('other-scope', 'new-job')
    assert repository.clear_pending('scope', 'new-job')
    assert repository.get('scope', 'pending') is None
    assert not repository.clear_pending('scope', 'new-job')


def test_concurrent_clear_of_same_pending_is_single_winner(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    repository.set('scope', 'pending', 'job')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repository.clear_pending('scope', 'job'), range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_append_session_preserves_parallel_tabs_and_is_unique(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    repository.append_session('subject', 'existing-session')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: repository.append_session('subject', f'session-{index % 8}'), range(32)))
    sessions = repository.get('subject', 'sessions')
    assert sessions[0] == 'existing-session'
    assert len(sessions) == 9
    assert set(sessions) == {'existing-session'} | {f'session-{index}' for index in range(8)}
    assert repository.append_session('other-subject', 'separate') == ['separate']
    assert repository.get('subject', 'sessions') == sessions


def test_append_session_refuses_corrupt_registry_without_reset(tmp_path):
    repository = LearningRepository(tmp_path / 'learning.sqlite3')
    repository.set('subject', 'sessions', {'unexpected': 'preserve'})
    with pytest.raises(ValueError, match='不正'):
        repository.append_session('subject', 'new')
    assert repository.get('subject', 'sessions') == {'unexpected': 'preserve'}
    with pytest.raises(ValueError):
        repository.append_session('other-subject', '')
    with pytest.raises(ValueError):
        repository.clear_pending('scope', '')


def test_practice_replacement_archives_latest_atomically_and_only_once(tmp_path):
    store = LearningRepository(tmp_path / 'learning.sqlite3')
    first = {'practice_id': 'first', 'questions': ['synthetic first']}
    second = {'practice_id': 'second', 'questions': ['synthetic second']}
    store.set('scope', 'practice_set', first)
    assert store.apply_result('new-job', 'scope', {'practice_set': second})
    assert store.get('scope', 'practice_set') == second
    assert store.get('scope', 'practice_archive:first') == first
    assert store.get('scope', 'practice_ids') == ['first']
    assert not store.apply_result('new-job', 'scope', {'practice_set': second})
    assert store.get('scope', 'practice_ids') == ['first']


def test_failed_practice_replacement_rolls_back_archive_and_receipt(tmp_path, monkeypatch):
    store = LearningRepository(tmp_path / 'learning.sqlite3')
    first = {'practice_id': 'first'}
    store.set('scope', 'practice_set', first)
    original = store._write

    def fail_on_replacement(db, scope, name, value):
        if name == 'practice_set':
            raise RuntimeError('synthetic disk failure')
        return original(db, scope, name, value)

    monkeypatch.setattr(store, '_write', fail_on_replacement)
    with pytest.raises(RuntimeError, match='synthetic disk failure'):
        store.apply_result('failed-job', 'scope', {'practice_set': {'practice_id': 'second'}})
    assert store.get('scope', 'practice_set') == first
    assert store.get('scope', 'practice_archive:first') is None
    assert store.get('scope', 'practice_ids') is None
    assert not store.has_receipt('failed-job', 'scope')


def test_simultaneous_practice_results_keep_every_set(tmp_path):
    store = LearningRepository(tmp_path / 'learning.sqlite3')
    store.set('scope', 'practice_set', {'practice_id': 'first'})
    barrier = threading.Barrier(2)

    def apply(pid):
        barrier.wait()
        return store.apply_result(pid, 'scope', {'practice_set': {'practice_id': pid}})

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(apply, ['second', 'third']))
    latest = store.get('scope', 'practice_set')['practice_id']
    ids = store.get('scope', 'practice_ids')
    assert len(ids) == 2 and set(ids + [latest]) == {'first', 'second', 'third'}
    assert all(store.get('scope', 'practice_archive:' + pid)['practice_id'] == pid for pid in ids)
