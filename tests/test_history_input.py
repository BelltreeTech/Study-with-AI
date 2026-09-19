"""Saved UI results are excluded from input sizing; conversation text stays bounded."""

import copy
import json

import pytest
from test_learning import FakeProvider
from test_lecture_context import RecordingRetriever

from src.config import LearningOptions
from src.service import StudyService


def prepare(history, **extra):
    return StudyService(FakeProvider(), RecordingRetriever()).prepare(
        "dialogue", "Synthetic/Study", "s", {"question": "Recall", "history": history, **extra}, LearningOptions()
    )


def test_saved_result_duplicate_does_not_reject_valid_8000_character_message():
    content = "学" * 8000
    history = [{"role": "assistant", "content": content, "material_revision": "synthetic-v1",
                "result": {"markdown": content, "supplemental_markdown": "保存表示用補足" * 4000,
                           "sources": [{"text": "synthetic source"}], "source_ids": ["S-synthetic"]}}]
    before = copy.deepcopy(history)
    assert len(json.dumps(history, ensure_ascii=False).encode()) > 48000
    request = prepare(history)
    assert request.payload["history"] == [{"role": "assistant", "content": content}]
    assert len(json.dumps(request.payload, ensure_ascii=False).encode()) < 48000
    assert history == before


def test_oversized_actual_content_and_unknown_metadata_still_fail():
    content = {"role": "assistant", "content": "学" * 16001, "material_revision": "synthetic-v1",
               "result": {"markdown": "storage only"}}
    with pytest.raises(ValueError, match="入力が長すぎます"):
        prepare([content])
    unknown_metadata = {"role": "assistant", "content": "valid", "material_revision": "synthetic-v1",
                        "unknown_metadata": "大" * 16001, "result": {"markdown": "storage only"}}
    with pytest.raises(ValueError, match="入力が長すぎます"):
        prepare([unknown_metadata])
    # Only the known assistant result gets the exception; user fields still count.
    with pytest.raises(ValueError, match="入力が長すぎます"):
        prepare([{"role": "user", "content": "valid", "result": {"large": "大" * 16001}}])
    with pytest.raises(ValueError, match="入力が長すぎます"):
        prepare([], other="大" * 16001)


@pytest.mark.parametrize("history", [
    None, "invalid", {"role": "assistant", "content": "text"}, ["text"], [None],
    [{"role": "system", "content": "text"}], [{"role": "assistant", "content": 123}],
    [{"role": "assistant"}], [{"role": "user", "content": "text", "material_revision": 123}],
    [{"role": "assistant", "content": "text", "result": "invalid"}],
], ids=["none", "string", "object", "string-item", "null-item", "role", "content", "missing-content",
        "revision", "saved-result"])
def test_malformed_history_has_clear_validation_error(history):
    with pytest.raises(ValueError, match="会話履歴"):
        prepare(history)


def test_non_json_unknown_metadata_is_rejected_clearly():
    with pytest.raises(ValueError, match="JSONで表せる"):
        prepare([{"role": "user", "content": "text", "unknown_metadata": {1, 2}}])


def test_twenty_message_window_and_revision_filter_are_preserved_without_text_truncation():
    history = [{"role": "assistant", "content": f"message-{index}", "material_revision": "synthetic-v1",
                "result": {"markdown": f"message-{index}"}} for index in range(25)]
    history[10]["material_revision"] = "old"
    request = prepare(history)
    assert [item["content"] for item in request.payload["history"]] == [
        f"message-{index}" for index in range(5, 25) if index != 10
    ]
    # The existing raw content bound applies even to old messages later filtered.
    history[0]["content"] = "大" * 16001
    with pytest.raises(ValueError, match="入力が長すぎます"):
        prepare(history)


def test_lecture_and_supplement_bounds_still_apply_after_history_storage_projection():
    history = [{"role": "assistant", "content": "Recall", "material_revision": "synthetic-v1",
                "result": {"markdown": "大" * 16001}}]
    with pytest.raises(ValueError, match="40000文字以内"):
        prepare(history, lecture="a" * 40001)
    with pytest.raises(ValueError, match="20000文字以内"):
        prepare(history, lecture_supplement="a" * 20001)
