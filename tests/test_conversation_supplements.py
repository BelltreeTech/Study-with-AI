"""New saved assistant turns retain the supplementary questions shown to the learner."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_learning import FakeProvider
from test_personalization import SyntheticRetriever

from src.config import LearningOptions
from src.learning_repository import LearningRepository
from src.service import StudyService
from src.views.common import _apply, scope_key


@pytest.mark.parametrize("kind", ["answer", "dialogue"])
def test_supplementary_question_survives_save_and_next_turn_without_rewriting_old_history(tmp_path, kind):
    service = StudyService(FakeProvider(), SyntheticRetriever())
    store = LearningRepository(tmp_path / "synthetic-learning.sqlite3")
    scope = scope_key("Synthetic/Study", "session", view=kind)
    legacy = {
        "role": "assistant",
        "content": "Legacy saved text stays exactly as stored.",
        "result": {
            "markdown": "Legacy saved text stays exactly as stored.",
            "supplemental_markdown": "Legacy omitted supplement is not rewritten.",
        },
        "material_revision": "synthetic-material-v1",
    }
    store.apply_result("legacy-job", scope, {}, message_pair=[legacy])
    request = service.prepare(kind, "Synthetic/Study", "session", {"question": "Explain recall."}, LearningOptions())
    result = service.execute(request)
    result["markdown"] = "Recalling without looking is different from rereading."
    result["supplemental_markdown"] = (
        "料理Aはレシピを見ながら、料理Bは思い出してから確認します。どちらが想起練習ですか？"
    )
    before_result = deepcopy(result)
    job = {"id": "new-job", "payload": request.to_dict(), "result": result}
    runtime = SimpleNamespace(store=store, service=service)
    _apply(runtime, scope, job)
    _apply(runtime, scope, job)  # Receipt replay cannot append or alter earlier turns.
    history = store.get(scope, "history")
    assert len(history) == 3 and history[0] == legacy
    saved = history[-1]
    assert saved["content"].startswith(result["markdown"])
    assert "一般的な補足（教材からの引用ではありません）" in saved["content"]
    assert result["supplemental_markdown"] in saved["content"]
    assert saved["result"] == result == before_result

    reopened = LearningRepository(store.path)
    followup = service.prepare(
        kind,
        "Synthetic/Study",
        "session",
        {
            "question": "Bだと思います。理由も説明したいです。",
            "history": reopened.get(scope, "history"),
        },
        LearningOptions(),
    )
    assert followup.payload["history"][-1] == {"role": "assistant", "content": saved["content"]}
    assert followup.payload["history"][0]["content"] == legacy["content"]


def test_empty_supplement_does_not_add_a_heading(tmp_path):
    service = StudyService(FakeProvider(), SyntheticRetriever())
    store = LearningRepository(tmp_path / "synthetic-learning.sqlite3")
    request = service.prepare("answer", "Synthetic/Study", "session", {"question": "Recall?"}, LearningOptions())
    result = service.execute(request)
    assert result["supplemental_markdown"] == ""
    scope = scope_key(request.subject, request.session_id, view="answer")
    _apply(
        SimpleNamespace(store=store, service=service),
        scope,
        {"id": "synthetic-job", "payload": request.to_dict(), "result": result},
    )
    assert store.get(scope, "history")[-1]["content"] == result["markdown"]
