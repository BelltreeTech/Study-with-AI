"""Synthetic batch orchestration through real private SQLite jobs; no Codex calls."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
from copy import deepcopy
from dataclasses import replace

import pytest
from test_jobs import wait_job
from test_personalization import SyntheticRetriever

from src.config import LearningOptions
from src.jobs import JobManager
from src.learning_repository import LearningRepository
from src.lecture_batches import LectureBatch, lecture_batch_scope
from src.service import StudyService


class SyntheticFailure(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("PRIVATE synthetic error must not become checkpoint diagnostics")


class BatchProvider:
    def __init__(self, count=3):
        self.count = count
        self.calls = []
        self.hook = None

    def generate(self, prompt, schema, cancel_event=None):
        data = json.loads(prompt.split("BEGIN_UNTRUSTED_DATA_JSON\n")[1].split("\nEND_UNTRUSTED_DATA_JSON")[0])
        self.calls.append(data)
        os.fstat(cancel_event.execution_lock_fd)
        if self.hook:
            self.hook(data, cancel_event)
        refs = [data["sources"][0]["source_id"]]
        if "sections" in schema["properties"]:
            return {
                "title": "Retrieval learning",
                "objectives": ["Explain retrieval"],
                "prerequisites": [],
                "requires_code": False,
                "requires_math": False,
                "source_ids": refs,
                "sections": [
                    {
                        "section_id": f"s{i + 1}",
                        "title": f"Recall section {i + 1}",
                        "objectives": [f"Apply retrieval {i + 1}"],
                        "topics": ["Retrieval"],
                        "coverage": ["prerequisites", "concepts", "worked_example", "pitfalls", "summary"],
                    }
                    for i in range(self.count)
                ],
            }
        section = data["input"]["section"]
        return {
            "section_id": section["section_id"],
            "markdown": f"Recall before rereading. [{refs[0]}]",
            "source_ids": refs,
            "supplemental_markdown": "",
            "insufficient_evidence": False,
            "summary": f"Remember {section['section_id']}",
            "covered_objectives": section["objectives"],
        }


class RevisionRetriever(SyntheticRetriever):
    current = "synthetic-material-v1"

    def revision(self, subject):
        return self.current


@pytest.fixture
def env(tmp_path):
    provider = BatchProvider()
    service = StudyService(provider, RevisionRetriever())
    store = LearningRepository(tmp_path / "synthetic-learning.sqlite3")
    manager = JobManager(tmp_path / "synthetic-jobs.sqlite3", poll_interval=0.01)
    yield provider, service, store, manager
    manager.shutdown()


def make_request(service, request_id="first", edition="edition-one", session="session-one", **payload):
    return service.prepare(
        "lecture_plan",
        "Synthetic/Study",
        session,
        {
            "title": "Retrieval",
            "description": "Learn retrieval and repeated practice.",
            "_chapter_index": 0,
            "_previous_lecture_id": None,
            "_edition_id": edition,
            "_batch_scope": lecture_batch_scope("Synthetic/Study", "course-one", 0),
            **payload,
        },
        LearningOptions(),
        course_id="course-one",
        request_id=request_id,
    )


def submit(env, request=None, *, deadline=1800, batch=None, key=None):
    provider, service, store, manager = env
    request = request or make_request(service)
    batch = batch or LectureBatch(service, store, deadline_seconds=deadline)
    job = manager.submit(
        "lecture_batch",
        request.payload["_batch_scope"],
        request.to_dict(),
        key or request.request_id,
        lambda cancel: batch.run(request, cancel),
    )
    return job


def checkpoint(store, request):
    return store.get(request.payload["_batch_scope"], "lecture_batch")


def test_maximum_nine_calls_preserves_each_checkpoint_and_replays_without_generation(env):
    provider, service, store, manager = env
    provider.count = 8
    req = make_request(service)
    snapshots = []
    provider.hook = lambda data, cancel: snapshots.append(deepcopy(checkpoint(store, req)))
    result = wait_job(manager, submit(env, req))
    assert result["state"] == "succeeded"
    assert len(provider.calls) == 9
    assert [len(item["sections"]) for item in snapshots] == [0, 0, 1, 2, 3, 4, 5, 6, 7]
    assert [item["input"].get("prior_summaries", []) for item in provider.calls[1:]] == [
        [{"section_id": f"s{i + 1}", "summary": f"Remember s{i + 1}"} for i in range(n)] for n in range(8)
    ]
    complete = checkpoint(store, req)
    assert complete["status"] == "succeeded" and len(complete["attempts"]) == 9
    assert all(item["status"] == "succeeded" for item in complete["attempts"])
    assert result["result"]["format"] == "sections-v1"
    assert result["result"]["lecture_id"] == req.payload["_edition_id"]
    assert result["result"]["sections"] == complete["sections"]
    assert submit(env, req) == result["id"]
    reopened = LearningRepository(store.path)
    resumed = replace(req, request_id="explicit-resume", session_id="new-session")
    repeat = wait_job(manager, submit(env, resumed, batch=LectureBatch(service, reopened)))
    assert repeat["result"] == result["result"] and len(provider.calls) == 9


@pytest.mark.parametrize("code", ["rate_limited", "network_error", "schema_error", "auth_required"])
def test_failure_stops_without_retry_and_restart_skips_successful_operations(env, code):
    provider, service, store, manager = env
    req = make_request(service)

    def fail_second_section(data, cancel):
        if data["input"].get("section", {}).get("section_id") == "s2":
            raise SyntheticFailure(code)

    provider.hook = fail_second_section
    failed = wait_job(manager, submit(env, req))
    assert failed["state"] == "failed" and failed["error_code"] == code
    partial = checkpoint(store, req)
    assert [item["section_id"] for item in partial["sections"]] == ["s1"]
    assert partial["status"] == "failed" and partial["attempts"][-1]["error_code"] == code
    assert "PRIVATE" not in json.dumps(partial)
    assert len(provider.calls) == 3
    # Merely replaying a failed request under another job key is not consent to retry.
    rejected = wait_job(manager, submit(env, req, key="same-failed-request"))
    assert rejected["error_code"] == "invalid_request" and len(provider.calls) == 3
    provider.hook = None
    new_request = replace(req, request_id="resume", session_id="after-restart")
    restarted = LectureBatch(service, LearningRepository(store.path))
    done = wait_job(manager, submit(env, new_request, batch=restarted))
    assert done["state"] == "succeeded" and len(provider.calls) == 5
    assert [call["input"]["section"]["section_id"] for call in provider.calls[3:]] == ["s2", "s3"]
    assert done["result"]["sections"][0] == partial["sections"][0]


@pytest.mark.parametrize("deadline", [False, True])
def test_cancel_or_deadline_stops_child_cleans_up_and_preserves_reason(env, deadline):
    provider, service, store, manager = env
    started, cleaned = threading.Event(), threading.Event()
    req = make_request(service)

    def blocking(data, cancel):
        if data["input"].get("section", {}).get("section_id") == "s2":
            started.set()
            assert cancel.wait(3)
            cleaned.set()
            raise SyntheticFailure("cancelled")

    provider.hook = blocking
    job_id = submit(env, req, deadline=0.8 if deadline else 1800)
    assert started.wait(2)
    if not deadline:
        manager.cancel(job_id)
    done = wait_job(manager, job_id)
    assert cleaned.is_set()
    assert done["state"] == ("failed" if deadline else "cancelled")
    assert done["error_code"] == ("timeout" if deadline else "cancelled")
    saved = checkpoint(store, req)
    assert len(provider.calls) == 3 and len(saved["sections"]) == 1
    assert saved["error_code"] == done["error_code"]


def test_material_change_rejects_late_section_and_does_not_continue(env):
    provider, service, store, manager = env
    req = make_request(service)

    def mutate_material(data, cancel):
        if data["input"].get("section", {}).get("section_id") == "s2":
            service.retriever.current = "synthetic-material-v2"

    provider.hook = mutate_material
    result = wait_job(manager, submit(env, req))
    assert result["state"] == "failed" and result["error_code"] == "invalid_result"
    assert len(provider.calls) == 3 and len(checkpoint(store, req)["sections"]) == 1
    resumed = replace(req, request_id="stale-resume")
    assert wait_job(manager, submit(env, resumed))["error_code"] == "invalid_result"
    assert len(provider.calls) == 3


@pytest.mark.parametrize("change", ["options", "sources", "model", "scope", "chapter", "revision"])
def test_resume_is_bound_to_original_inputs_and_configuration(env, change):
    provider, service, store, manager = env
    req = make_request(service)
    assert wait_job(manager, submit(env, req))["state"] == "succeeded"
    changed = replace(req, request_id="changed")
    if change == "options":
        changed = replace(changed, options=LearningOptions(learning_goal="Changed learning target"))
    elif change == "sources":
        changed = replace(changed, sources=[{**req.sources[0], "text": "Different evidence"}])
    elif change == "model":
        changed = replace(changed, model="not-authorized")
    elif change == "scope":
        changed = replace(changed, payload=req.payload | {"_batch_scope": "another-scope"})
    elif change == "chapter":
        changed = replace(changed, payload=req.payload | {"_chapter_index": 1})
    else:
        changed = replace(changed, material_revision="other-revision")
    rejected = wait_job(manager, submit(env, changed))
    assert rejected["state"] == "failed" and len(provider.calls) == 4
    assert checkpoint(store, req)["status"] == "succeeded"


def test_corrupt_checkpoint_fails_closed_without_replacing_it(env):
    provider, service, store, manager = env
    req = make_request(service)
    assert wait_job(manager, submit(env, req))["state"] == "succeeded"
    name = "lecture_batch:" + req.payload["_edition_id"]
    corrupt = store.get(req.payload["_batch_scope"], name)
    corrupt["sections"][0]["markdown"] = "unverified replacement"
    store.set(req.payload["_batch_scope"], name, corrupt)
    result = wait_job(manager, submit(env, replace(req, request_id="corrupt-resume")))
    assert result["error_code"] == "invalid_result" and len(provider.calls) == 4
    assert store.get(req.payload["_batch_scope"], name) == corrupt


def test_new_edition_retains_previous_checkpoint(env):
    provider, service, store, manager = env
    req = make_request(service)
    original = wait_job(manager, submit(env, req))
    archive = deepcopy(checkpoint(store, req))
    replacement = make_request(
        service, request_id="regenerate", edition="edition-two", _previous_lecture_id="edition-one"
    )
    newer = wait_job(manager, submit(env, replacement))
    assert original["state"] == newer["state"] == "succeeded"
    assert store.get(req.payload["_batch_scope"], "lecture_batch:edition-one") == archive
    assert checkpoint(store, req)["edition_id"] == "edition-two"


def test_global_lock_stays_held_between_sections_and_reaches_every_child(env):
    provider, service, store, manager = env
    second = JobManager(manager.db_path, poll_interval=0.01)
    sequence = []
    started, release = threading.Event(), threading.Event()

    def hook(data, cancel):
        sequence.append(data["input"].get("section", {}).get("section_id", "plan"))
        with open(manager.lock_path, "rb") as file:
            with pytest.raises(BlockingIOError):
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if len(sequence) == 1:
            started.set()
            assert release.wait(3)

    provider.hook = hook
    try:
        first_job = submit(env)
        assert started.wait(2)
        other = second.submit("answer", "other", {}, "other", lambda cancel: sequence.append("other") or {})
        assert second.get(other)["state"] == "queued"
        release.set()
        assert wait_job(manager, first_job)["state"] == "succeeded"
        assert wait_job(second, other)["state"] == "succeeded"
        assert sequence == ["plan", "s1", "s2", "s3", "other"]
    finally:
        release.set()
        second.shutdown()


def test_atomic_checkpoint_compare_does_not_overwrite_concurrent_mutation(env):
    provider, service, store, manager = env
    req = make_request(service)
    changed = None

    def race(data, cancel):
        nonlocal changed
        if data["input"].get("section", {}).get("section_id") == "s1":
            name = "lecture_batch:edition-one"
            changed = store.get(req.payload["_batch_scope"], name)
            changed["external_change"] = "preserve"
            store.set(req.payload["_batch_scope"], name, changed)

    provider.hook = race
    result = wait_job(manager, submit(env, req))
    assert result["error_code"] == "invalid_result" and len(provider.calls) == 2
    assert store.get(req.payload["_batch_scope"], "lecture_batch:edition-one") == changed


def test_repository_atomic_document_mirror_rolls_back_together(env):
    _, _, store, _ = env
    store.update_document("synthetic", "edition", lambda old: {"part": 1}, mirror_name="current")

    def fail(old):
        old["part"] = 2
        raise ValueError("synthetic failure")

    with pytest.raises(ValueError):
        store.update_document("synthetic", "edition", fail, mirror_name="current")
    assert store.get("synthetic", "edition") == store.get("synthetic", "current") == {"part": 1}


def test_parent_generation_lock_is_required_before_state_or_generation(env):
    provider, service, store, _ = env
    req = make_request(service)
    with pytest.raises(RuntimeError) as error:
        LectureBatch(service, store).run(req, threading.Event())
    assert error.value.code == "invalid_request"
    assert provider.calls == [] and checkpoint(store, req) is None


def test_process_crash_preserves_partial_and_explicit_resume_skips_successes(env):
    provider, service, store, manager = env
    script = """
import os, sys, time
sys.path.insert(0, 'tests')
from test_lecture_batches import BatchProvider, RevisionRetriever, make_request
from src.service import StudyService
from src.jobs import JobManager
from src.learning_repository import LearningRepository
from src.lecture_batches import LectureBatch
provider = BatchProvider()
service = StudyService(provider, RevisionRetriever())
store = LearningRepository(sys.argv[1])
manager = JobManager(sys.argv[2], poll_interval=.01)
request = make_request(service)
def crash(data, cancel):
    if data['input'].get('section', {}).get('section_id') == 's2':
        os._exit(0)
provider.hook = crash
batch = LectureBatch(service, store)
manager.submit('lecture_batch', request.payload['_batch_scope'], request.to_dict(),
               request.request_id, lambda cancel: batch.run(request, cancel))
time.sleep(10)
raise SystemExit(1)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(store.path), str(manager.db_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _, stderr = child.communicate(timeout=7)
        assert child.returncode == 0, stderr.decode()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()
    req = make_request(service)
    partial = checkpoint(store, req)
    assert partial["status"] == "running" and len(partial["sections"]) == 1
    assert partial["attempts"][-1]["status"] == "running"
    assert provider.calls == []  # Restart/recovery itself consumes no generation.
    resumed = replace(req, request_id="explicit-after-crash", session_id="new-session")
    result = wait_job(manager, submit(env, resumed))
    assert result["state"] == "succeeded"
    assert [call["input"]["section"]["section_id"] for call in provider.calls] == ["s2", "s3"]
    saved = checkpoint(store, req)
    assert [item["status"] for item in saved["attempts"]] == [
        "succeeded",
        "succeeded",
        "interrupted",
        "succeeded",
        "succeeded",
    ]
    assert saved["sections"][0] == partial["sections"][0]


def test_invalid_plan_cannot_exceed_eight_sections_or_trigger_more_calls(env):
    provider, service, store, manager = env
    provider.count = 9
    request = make_request(service)
    failed = wait_job(manager, submit(env, request))
    assert failed["state"] == "failed" and failed["error_code"] == "invalid_result"
    assert len(provider.calls) == 1 and checkpoint(store, request)["sections"] == []


def test_document_compare_and_mirror_roll_back_if_json_cannot_be_saved(env):
    _, _, store, _ = env
    store.update_document("synthetic", "edition", lambda old: {"value": 1}, mirror_name="current")
    with pytest.raises(ValueError):
        store.update_document("synthetic", "edition", lambda old: {"value": float("nan")}, mirror_name="current")
    assert store.get("synthetic", "edition") == store.get("synthetic", "current") == {"value": 1}


@pytest.mark.parametrize("cancelled", [True, False])
def test_failed_replay_does_not_rewrite_completed_edition(env, cancelled):
    provider, service, store, manager = env
    request = make_request(service)
    assert wait_job(manager, submit(env, request))["state"] == "succeeded"
    original = checkpoint(store, request)
    replay = replace(request, request_id="replay")
    batch = LectureBatch(service, store)

    def worker(cancel):
        if cancelled:
            cancel.set()
        else:
            service.retriever.current = "new-material-revision"
        return batch.run(replay, cancel)

    job = manager.submit("lecture_batch", request.payload["_batch_scope"], replay.to_dict(), "replay", worker)
    failed = wait_job(manager, job)
    assert failed["error_code"] == ("cancelled" if cancelled else "invalid_result")
    assert checkpoint(store, request) == original and len(provider.calls) == 4


def test_schema_diagnostic_survives_batch_wrapping_and_checkpoint(env):
    from src.codex_provider import ProviderError

    provider, service, store, manager = env
    req = make_request(service)
    def fail_plan(data, cancel):
        raise ProviderError('schema_error', 'PRIVATE raw error', diagnostic={
            'category': 'schema_validation', 'keyword': 'maxLength',
            'path': ['sections', 0, 'title'], 'limit': 80, 'actual': 81})
    provider.hook = fail_plan
    result = wait_job(manager, submit(env, req))
    saved = checkpoint(store, req)
    assert len(provider.calls) == 1 and saved['plan'] is None and saved['sections'] == []
    assert saved['attempts'][-1]['diagnostic'] == result['diagnostic']
    assert result['diagnostic']['stage'] == 'lecture_plan'
    assert '講義設計' in result['error_message'] and '81' in result['error_message']
    assert 'PRIVATE' not in json.dumps(saved)


def test_section_timeout_identifies_stage_and_preserves_successful_sections(env):
    from src.codex_provider import ProviderError

    provider, service, store, manager = env
    req = make_request(service)
    def fail_second(data, cancel):
        if data['input'].get('section', {}).get('section_id') == 's2':
            raise ProviderError('timeout', 'synthetic timeout', diagnostic={'category': 'timeout', 'limit': 180})
    provider.hook = fail_second
    job = wait_job(manager, submit(env, req))
    assert job['diagnostic'] == {'category': 'timeout', 'stage': 'lecture_section', 'limit': 180,
                                 'path': ['sections', 1]}
    assert '第2節' in job['error_message'] and '180秒' in job['error_message']
    saved = checkpoint(store, req)
    assert len(saved['sections']) == 1 and len(provider.calls) == 3
    assert saved['attempts'][-1]['diagnostic'] == job['diagnostic']
