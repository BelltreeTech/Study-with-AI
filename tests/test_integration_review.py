"""Focused independent-review regressions using synthetic repositories and results."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_learning import FakeProvider

from src import progress
from src.config import LearningOptions
from src.learning_repository import LearningRepository
from src.schemas import InvalidResult
from src.service import StudyService
from src.views import common
from src.views.view_curriculum import _export

SUBJECT = "Synthetic/Review"
SESSION = "session-review"
COURSE = "synthetic-course"
REVISION = "synthetic-material-v1"


class SyntheticRetriever:
    current_revision = REVISION

    def revision(self, subject):
        assert subject == SUBJECT
        return self.current_revision

    def search(self, subject, query, top_k=5):
        assert subject == SUBJECT
        return [
            {
                "source_id": "S-synthetic",
                "source_file": "Synthetic/Review/example.pdf",
                "chunk_id": "chunk-synthetic",
                "page_number": 1,
                "text": "Spaced retrieval supports memory.",
            }
        ]


@pytest.fixture
def review_runtime(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(progress, "k_progressDir", state)
    monkeypatch.setattr(progress, "k_progressFile", state / "progress.json")
    retriever = SyntheticRetriever()
    provider = FakeProvider()
    runtime = SimpleNamespace(
        store=LearningRepository(state / "learning.sqlite3"),
        retriever=retriever,
        service=StudyService(provider, retriever),
        provider=provider,
        jobs=SimpleNamespace(get=Mock(), submit=Mock()),
    )
    progress.save_course_progress(
        COURSE,
        [
            {
                "chapter": 1,
                "title": "Recall",
                "status": "unlocked",
                "lecture_content": {
                    "markdown": "Synthetic lecture one",
                    "lecture_id": "lecture-0",
                    "material_revision": REVISION,
                },
            },
            {
                "chapter": 2,
                "title": "Spacing",
                "status": "locked",
                "lecture_content": {
                    "markdown": "Synthetic lecture two",
                    "lecture_id": "lecture-1",
                    "material_revision": REVISION,
                },
            },
        ],
        0,
        metadata={"subject": SUBJECT},
    )
    return runtime


def course_grade(runtime, index=0):
    request = runtime.service.prepare(
        "quiz",
        SUBJECT,
        SESSION,
        {
            "topic": "recall",
            "lecture": "Synthetic lecture",
            "lecture_revision": REVISION,
            "chapter_index": index,
            "lecture_id": f"lecture-{index}",
        },
        LearningOptions(),
        course_id=COURSE,
    )
    exam = runtime.service.execute(request)
    grading = runtime.service.prepare(
        "grade", SUBJECT, SESSION, {"exam": exam, "answer": "Recall then review."}, LearningOptions(), course_id=COURSE
    )
    result = runtime.service.execute(grading)
    scope = common.scope_key(SUBJECT, SESSION, COURSE, str(index), f"exam:lecture-{index}")
    runtime.store.set(scope, "quiz", exam)
    job = {"id": f"grade-job-{index}", "state": "succeeded", "payload": grading.to_dict(), "result": result}
    return scope, job


def test_chapter_completion_is_bound_to_grade_chapter_and_awards_once(review_runtime):
    runtime = review_runtime
    scope, job = course_grade(runtime)
    assert job["result"]["chapter_index"] == 0 and job["result"]["lecture_id"] == "lecture-0"
    common._apply(runtime, scope, job)
    attempt = job["result"]["attempt_id"]
    assert progress.complete_chapter(COURSE, 0, attempt, material_revision=REVISION)
    assert not progress.complete_chapter(COURSE, 0, attempt, material_revision=REVISION)
    with pytest.raises(ValueError, match="一致"):
        progress.complete_chapter(COURSE, 1, attempt, material_revision=REVISION)
    course = progress.load_course_progress(COURSE)
    assert course["exp"] == 50
    assert course["curriculum"][0]["status"] == "completed"
    assert course["curriculum"][1]["status"] == "unlocked"


@pytest.mark.parametrize("change", ["material", "lecture"])
def test_completion_rejects_changed_material_or_regenerated_lecture(review_runtime, change):
    runtime = review_runtime
    scope, job = course_grade(runtime)
    common._apply(runtime, scope, job)
    current_revision = REVISION
    if change == "material":
        current_revision = "synthetic-material-v2"
    else:

        def replace_lecture(data):
            data["courses"][COURSE]["curriculum"][0]["lecture_content"]["lecture_id"] = "regenerated-lecture"

        progress.get_repository().update(replace_lecture)
    with pytest.raises(ValueError):
        progress.complete_chapter(COURSE, 0, job["result"]["attempt_id"], material_revision=current_revision)
    course = progress.load_course_progress(COURSE)
    assert course.get("exp", 0) == 0
    assert course["curriculum"][0]["status"] == "unlocked"


def test_completion_patches_latest_course_without_losing_other_chapter(review_runtime):
    runtime = review_runtime
    scope, job = course_grade(runtime)
    common._apply(runtime, scope, job)

    def save_sibling(data):
        data["courses"][COURSE]["curriculum"][1]["lecture_content"]["markdown"] = "Concurrent lecture saved"
        data["courses"][COURSE]["unknown"] = {"preserve": True}

    progress.get_repository().update(save_sibling)
    progress.complete_chapter(COURSE, 0, job["result"]["attempt_id"], material_revision=REVISION)
    course = progress.load_course_progress(COURSE)
    assert course["curriculum"][1]["lecture_content"]["markdown"] == "Concurrent lecture saved"
    assert course["unknown"] == {"preserve": True}


def test_late_grade_cannot_apply_to_reset_attempt(review_runtime):
    runtime = review_runtime
    scope, job = course_grade(runtime)
    runtime.store.set(scope, "quiz", None)
    with pytest.raises(ValueError, match="試験が変更"):
        common._apply(runtime, scope, job)
    assert not progress.load_course_progress(COURSE).get("grade_history")
    assert not runtime.store.has_receipt(job["id"], scope)


def test_late_grade_cannot_apply_to_regenerated_lecture(review_runtime):
    runtime = review_runtime
    scope, job = course_grade(runtime)

    def regenerate(data):
        data["courses"][COURSE]["curriculum"][0]["lecture_content"]["lecture_id"] = "new-lecture"

    progress.get_repository().update(regenerate)
    with pytest.raises(ValueError, match="章・講義"):
        common._apply(runtime, scope, job)
    assert not progress.load_course_progress(COURSE).get("grade_history")


def test_course_quiz_requires_application_owned_chapter_metadata(review_runtime):
    with pytest.raises(InvalidResult, match="章番号と講義ID"):
        review_runtime.service.prepare(
            "quiz", SUBJECT, SESSION, {"topic": "recall"}, LearningOptions(), course_id=COURSE
        )
    with pytest.raises(InvalidResult, match="章番号と講義ID"):
        review_runtime.service.prepare(
            "quiz",
            SUBJECT,
            SESSION,
            {"topic": "recall", "chapter_index": True, "lecture_id": "id"},
            LearningOptions(),
            course_id=COURSE,
        )


def test_receipt_replay_skips_revision_validation_and_progress(review_runtime, monkeypatch):
    runtime = review_runtime
    scope = common.scope_key(SUBJECT, SESSION, view="rag")
    runtime.store.apply_result("already-applied", scope, {"answer": "preserved"})
    validate = Mock(side_effect=AssertionError("Replay must not revalidate or reapply"))
    monkeypatch.setattr(runtime.service, "validate_revision", validate)
    common._apply(runtime, scope, {"id": "already-applied"})
    validate.assert_not_called()
    assert runtime.store.get(scope, "answer") == "preserved"


class RerunRequested(Exception):
    pass


def minimal_ui(monkeypatch, *, button=False):
    ui = SimpleNamespace(
        session_state={
            "selected_subject": SUBJECT,
            "study_session": SESSION,
            "learning_options": asdict(LearningOptions()),
        },
        info=Mock(),
        error=Mock(),
        caption=Mock(),
        button=Mock(return_value=button),
        rerun=Mock(side_effect=RerunRequested()),
    )
    monkeypatch.setattr(common, "st", ui)
    return ui


def test_rejected_success_can_be_explicitly_released(review_runtime, monkeypatch):
    runtime = review_runtime
    scope = common.scope_key(SUBJECT, SESSION, view="rag")
    request = runtime.service.prepare("answer", SUBJECT, SESSION, {"question": "recall"}, LearningOptions())
    runtime.store.set(scope, "pending", "old-success")
    runtime.jobs.get.return_value = {
        "id": "old-success",
        "state": "succeeded",
        "payload": request.to_dict(),
        "result": {"markdown": "obsolete"},
    }
    runtime.retriever.current_revision = "changed-material"
    ui = minimal_ui(monkeypatch, button=True)
    with pytest.raises(RerunRequested):
        common.render_pending(runtime, scope)
    assert ui.error.called
    assert runtime.store.get(scope, "pending") is None
    assert runtime.store.get(scope, "rejected_result")["job_id"] == "old-success"
    assert runtime.store.claim_submission(scope, lambda: "new-request", lambda _: True) == ("new-request", True)


def test_render_pending_uses_compare_and_clear_after_apply(review_runtime, monkeypatch):
    runtime = review_runtime
    scope = common.scope_key(SUBJECT, SESSION, view="rag")
    runtime.store.set(scope, "pending", "completed-job")
    runtime.jobs.get.return_value = {"id": "completed-job", "state": "succeeded"}
    # Another tab replaces the pointer between reading the old job and clearing it.
    monkeypatch.setattr(common, "_apply", lambda *args: runtime.store.set(scope, "pending", "new-job"))
    minimal_ui(monkeypatch)
    with pytest.raises(RerunRequested):
        common.render_pending(runtime, scope)
    assert runtime.store.get(scope, "pending") == "new-job"


def test_grade_is_checked_again_inside_submission_claim(review_runtime, monkeypatch):
    runtime = review_runtime
    scope, job = course_grade(runtime)
    request_data = deepcopy(job["payload"])
    from src.service import LearningRequest

    request = LearningRequest.from_dict(request_data)

    def prepare(*args, **kwargs):
        # The first tab finishes while a second tab prepares its submission.
        runtime.store.set(scope, "grade", job["result"])
        return request

    monkeypatch.setattr(runtime.service, "prepare", prepare)
    ui = minimal_ui(monkeypatch)
    common.submit(runtime, scope, "grade", request.payload, course_id=COURSE)
    runtime.jobs.submit.assert_not_called()
    assert "採点済み" in ui.error.call_args.args[0]


def test_legacy_export_accepts_missing_chapter_number_and_null_lecture():
    output = _export({"title": "Legacy synthetic", "curriculum": [{"title": "Old chapter", "lecture_content": None}]})
    assert "第1章" in output and "Old chapter" in output and "講義未生成" in output


def test_older_lecture_job_cannot_overwrite_newer_session_result(review_runtime):
    runtime = review_runtime
    payload = {"title": "Recall", "_chapter_index": 0, "_previous_lecture_id": "lecture-0"}
    requests = [
        runtime.service.prepare("lecture", SUBJECT, session, payload, LearningOptions(), course_id=COURSE)
        for session in ("first-session", "second-session")
    ]
    jobs = [
        {"id": name, "state": "succeeded", "payload": request.to_dict(), "result": runtime.service.execute(request)}
        for name, request in zip(("new-lecture-result", "late-lecture-result"), requests, strict=True)
    ]
    common._apply(runtime, common.scope_key(SUBJECT, "first-session", COURSE, "0", "lecture"), jobs[0])
    with pytest.raises(ValueError, match="別の学習セッション"):
        common._apply(runtime, common.scope_key(SUBJECT, "second-session", COURSE, "0", "lecture"), jobs[1])
    assert (
        progress.load_course_progress(COURSE)["curriculum"][0]["lecture_content"]["lecture_id"] == "new-lecture-result"
    )
