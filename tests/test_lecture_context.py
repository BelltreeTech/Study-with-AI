"""Long saved lectures remain usable with bounded, explicit offline excerpts."""

import json

import pytest
from test_course_context import MissingEmbedder, make_pdf
from test_learning import FakeProvider

from src.config import LearningOptions
from src.lecture_context import select_lecture_context, select_lecture_material
from src.retriever import LocalRetriever
from src.schemas import SCHEMAS, InvalidResult, validate_schema
from src.service import StudyService


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    def revision(self, subject):
        return "synthetic-v1"

    def search(self, subject, query, top_k=5):
        self.calls.append((subject, query, top_k))
        return [{"source_id": "S-synthetic", "source_file": "Synthetic/Study/notes.pdf", "page_number": 1,
                 "chunk_id": "synthetic", "text": "Retrieval practice means recalling before rereading."}]


def long_lecture():
    parts = [f"## Section {i}\n" + f"Concept {i} describes study principles. " * 24 for i in range(28)]
    parts[14] = "## Target exercise\nTARGET_EXERCISE explains differential transfer. [S-late-citation]\n" + "Example. " * 70
    return "OPENING_SENTINEL\n\n" + "\n\n".join(parts) + "\n\nFINAL_CHECK_SENTINEL [S-final-citation]"


def test_short_lecture_is_retained_verbatim():
    text = "Short lecture. [S-synthetic]"
    selected, context = select_lecture_context(text, "lecture")
    assert selected == text
    assert context["is_excerpt"] is False
    assert context["total_chars"] == context["selected_chars"] == context["context_chars"] == len(text)
    assert context["ranges"] == [{"start": 0, "end": len(text), "reason": "complete"}]


def test_long_lecture_keeps_opening_tail_and_relevant_later_citation():
    text = long_lecture()
    selected, context = select_lecture_context(text, "Explain TARGET_EXERCISE differential transfer")
    assert len(text) > 20000 and len(selected) <= 6000
    assert "OPENING_SENTINEL" in selected and "FINAL_CHECK_SENTINEL [S-final-citation]" in selected
    assert "TARGET_EXERCISE" in selected and "[S-late-citation]" in selected
    assert context["is_excerpt"] and context["total_chars"] == len(text)
    assert context["context_chars"] == len(selected)
    assert context["selected_chars"] == sum(item["end"] - item["start"] for item in context["ranges"])
    assert {item["reason"] for item in context["ranges"]} >= {"opening", "ending", "query_relevance", "section_spread"}
    previous_end = 0
    for item in context["ranges"]:
        assert previous_end <= item["start"] < item["end"] <= len(text)
        assert text[item["start"]:item["end"]] in selected
        previous_end = item["end"]
    assert select_lecture_context(text, "Explain TARGET_EXERCISE differential transfer") == (selected, context)


@pytest.mark.parametrize("kind", ["dialogue", "quiz"])
def test_maximum_schema_valid_japanese_lecture_can_prepare_and_retains_ending(kind):
    text = ("学習の基本を説明します。\n\n" * 4000)[:39970] + "最後の確認: FINAL_SENTINEL"
    validate_schema({"markdown": text, "source_ids": ["S-synthetic"], "supplemental_markdown": "",
                     "insufficient_evidence": False}, SCHEMAS["lecture"])
    retriever, provider = RecordingRetriever(), FakeProvider()
    service = StudyService(provider, retriever)
    payload = {"question": "最後の確認を説明してください", "topic": "章の確認", "lecture": text,
               "lecture_revision": "synthetic-v1", "chapter_index": 0, "lecture_id": "saved-lecture"}
    request = service.prepare(kind, "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    assert len(request.payload["lecture"]) <= 6000
    assert "FINAL_SENTINEL" in request.payload["lecture"]
    assert request.payload["lecture_context"]["total_chars"] == len(text)
    assert payload["lecture"] == text
    assert provider.calls == []
    assert retriever.calls[0][0] == "Synthetic/Study"
    assert "FINAL_SENTINEL" in retriever.calls[0][1]


@pytest.mark.parametrize("bad", [None, 42, ["lecture"], {"text": "lecture"}, "a" * 40001],
                         ids=["none", "number", "list", "object", "too-long"])
def test_invalid_or_oversized_lecture_is_rejected_before_retrieval(bad):
    retriever = RecordingRetriever()
    with pytest.raises(ValueError, match="40000文字以内"):
        StudyService(FakeProvider(), retriever).prepare(
            "dialogue", "Synthetic/Study", "session", {"question": "explain", "lecture": bad}, LearningOptions()
        )
    assert retriever.calls == []


@pytest.mark.parametrize("large_field", ["question", "other", "lecture_context"])
def test_other_payload_fields_keep_the_byte_limit(large_field):
    retriever = RecordingRetriever()
    payload = {"question": "explain", "lecture": long_lecture(), "lecture_revision": "synthetic-v1"}
    payload[large_field] = "大" * 16001
    with pytest.raises(ValueError, match="入力が長すぎます"):
        StudyService(FakeProvider(), retriever).prepare("dialogue", "Synthetic/Study", "s", payload, LearningOptions())
    assert retriever.calls == []


def test_combined_selected_lecture_and_history_still_share_original_input_budget():
    payload = {"question": "explain", "lecture": "長い講義本文。" * 4000, "lecture_revision": "synthetic-v1",
               "history": [{"role": "user", "content": "履" * 12000, "material_revision": "synthetic-v1"}]}
    with pytest.raises(ValueError, match="入力が長すぎます"):
        StudyService(FakeProvider(), RecordingRetriever()).prepare(
            "dialogue", "Synthetic/Study", "s", payload, LearningOptions()
        )


def test_application_owns_lecture_coverage_metadata():
    payload = {"question": "explain", "lecture": long_lecture(), "lecture_revision": "synthetic-v1",
               "lecture_context": {"is_excerpt": False, "total_chars": 1, "forged": True}}
    request = StudyService(FakeProvider(), RecordingRetriever()).prepare(
        "dialogue", "Synthetic/Study", "s", payload, LearningOptions()
    )
    assert request.payload["lecture_context"]["is_excerpt"] is True
    assert "forged" not in request.payload["lecture_context"]


def test_stale_lecture_is_rejected_before_its_words_reach_retrieval():
    retriever = RecordingRetriever()
    with pytest.raises(InvalidResult, match="revisionが古い"):
        StudyService(FakeProvider(), retriever).prepare(
            "dialogue", "Synthetic/Study", "s", {"question": "explain", "lecture": "stale concepts",
                                                   "lecture_revision": "old"}, LearningOptions()
        )
    assert retriever.calls == []


def test_lecture_description_and_saved_lecture_help_bm25_without_overview_fallback(tmp_path):
    make_pdf(tmp_path / "data/Synthetic/Study/notes.pdf", ["Retrieval practice and spaced repetition support memory."])
    make_pdf(tmp_path / "data/Synthetic/Other/notes.pdf", ["Other-subject unique confidential example."])
    retriever = LocalRetriever(tmp_path / "data", tmp_path / "cache", embedder=MissingEmbedder())
    service = StudyService(FakeProvider(), retriever)
    generic_question = "この章の大切な考え方をやさしく説明してください"
    assert retriever.search("Synthetic/Study", generic_question) == []
    lecture = service.prepare("lecture", "Synthetic/Study", "s",
                              {"title": "総括と実践", "description": "Retrieval practice and spaced repetition"},
                              LearningOptions())
    assert lecture.sources
    for kind in ("dialogue", "quiz"):
        request = service.prepare(kind, "Synthetic/Study", "s", {
            "question": generic_question, "topic": "この章の確認", "lecture": "Retrieval practice helps memory.",
            "lecture_revision": retriever.revision("Synthetic/Study"),
        }, LearningOptions())
        assert request.sources and all(item["source_file"].startswith("Synthetic/Study/") for item in request.sources)
    with pytest.raises(InvalidResult, match="根拠を取得できません"):
        service.prepare("dialogue", "Synthetic/Study", "s", {
            "question": generic_question, "lecture": "全く無関係な話です", "lecture_revision": retriever.revision("Synthetic/Study"),
        }, LearningOptions())


def test_prompt_and_exam_grade_results_keep_explicit_excerpt_contract():
    retriever, provider = RecordingRetriever(), FakeProvider()
    service = StudyService(provider, retriever)
    payload = {"question": "Explain TARGET_EXERCISE", "lecture": long_lecture(), "lecture_revision": "synthetic-v1"}
    for kind in ("dialogue", "quiz"):
        request = service.prepare(kind, "Synthetic/Study", "s", payload, LearningOptions())
        result = service.execute(request)
        assert result["lecture_context"] == request.payload["lecture_context"]
        prompt = provider.calls[-1]
        assert "講義全体を確認・網羅したとは述べない" in prompt
        assert "相談・出題は選んだ範囲と教材根拠で扱える内容に限定" in prompt
        data = json.loads(prompt.split("BEGIN_UNTRUSTED_DATA_JSON\n", 1)[1].split("\nEND_UNTRUSTED_DATA_JSON", 1)[0])
        assert "[S-late-citation]" in data["input"]["lecture"]
        if kind == "quiz":
            grade = service.execute(service.prepare("grade", "Synthetic/Study", "s",
                                                     {"exam": result, "answer": "Recall first."}, LearningOptions()))
            assert grade["lecture_context"] == result["lecture_context"]


def test_short_main_and_supplement_keep_second_example_and_distinction():
    main = "定義と比較表。" * 150
    supplement = "例題1: 料理で検索練習を説明します。\n\n" * 80 + "例題2: SECOND_EXAMPLE_SENTINEL\n最後の練習手順。"
    selected_main, selected_supplement, context = select_lecture_material(main, supplement, "例題2について")
    assert main in selected_main and supplement in selected_supplement
    assert "SECOND_EXAMPLE_SENTINEL" in selected_supplement
    assert "一般的補足（教材原文ではありません）" in selected_supplement
    assert "SECOND_EXAMPLE_SENTINEL" not in selected_main
    assert not context["is_excerpt"]
    assert context["total_chars"] == context["selected_chars"] == len(main) + len(supplement)
    assert context["context_chars"] == len(selected_main) + len(selected_supplement) <= 6000
    assert context["sections"]["lecture_supplement"]["content_kind"] == "general_supplement_not_material"
    assert {item["field"] for item in context["ranges"]} == {"lecture", "lecture_supplement"}


def test_long_both_sections_keep_relevant_late_example_and_both_endings():
    main = "MAIN_OPENING\n\n" + ("## Main section\n本体の定義と重要事項。\n\n" * 700) + "\nMAIN_ENDING"
    supplement = "SUPPLEMENT_OPENING\n\n" + ("## Practice\n補足の練習です。\n\n" * 350)
    supplement += "\n\n例題2: SECOND_EXAMPLE_SENTINEL explains transfer. [S-example]\n\n" + "別の練習。" * 350
    supplement += "\nSUPPLEMENT_ENDING"
    selected_main, selected_supplement, context = select_lecture_material(
        main, supplement, "SECOND_EXAMPLE_SENTINEL transfer 例題2"
    )
    assert context["is_excerpt"]
    assert "MAIN_OPENING" in selected_main and "MAIN_ENDING" in selected_main
    assert "SUPPLEMENT_OPENING" in selected_supplement and "SUPPLEMENT_ENDING" in selected_supplement
    assert "SECOND_EXAMPLE_SENTINEL explains transfer. [S-example]" in selected_supplement
    assert len(selected_main) + len(selected_supplement) <= 6000
    assert context["sections"]["lecture"]["selected_chars"] > 500
    assert context["sections"]["lecture_supplement"]["selected_chars"] > 500
    fields = {"lecture": main, "lecture_supplement": supplement}
    selected = {"lecture": selected_main, "lecture_supplement": selected_supplement}
    for item in context["ranges"]:
        assert fields[item["field"]][item["start"]:item["end"]] in selected[item["field"]]
    assert context["selected_chars"] == sum(item["end"] - item["start"] for item in context["ranges"])


@pytest.mark.parametrize("kind", ["dialogue", "quiz"])
def test_maximum_japanese_main_and_supplement_fit_one_selected_context(kind):
    main = "本文。" * 13333 + "。"
    supplement = "補足。" * 6666 + "終。"
    assert len(main) == 40000 and len(supplement) == 20000
    retriever, provider = RecordingRetriever(), FakeProvider()
    request = StudyService(provider, retriever).prepare(kind, "Synthetic/Study", "s", {
        "question": "補足の練習", "lecture": main, "lecture_supplement": supplement,
        "lecture_revision": "synthetic-v1",
    }, LearningOptions())
    assert request.payload["lecture_context"]["total_chars"] == 60000
    assert len(request.payload["lecture"]) + len(request.payload["lecture_supplement"]) <= 6000
    assert len(json.dumps(request.payload, ensure_ascii=False).encode()) <= 48000
    assert request.payload["lecture_supplement"].startswith("[一般的補足（教材原文ではありません）]")
    assert provider.calls == []


@pytest.mark.parametrize("bad", [None, 42, ["supplement"], {"supplement": "x"}, "a" * 20001],
                         ids=["none", "number", "list", "object", "too-long"])
def test_supplement_independent_type_and_size_bounds(bad):
    retriever = RecordingRetriever()
    with pytest.raises(ValueError, match="一般的補足は20000文字以内"):
        StudyService(FakeProvider(), retriever).prepare("dialogue", "Synthetic/Study", "s", {
            "question": "explain", "lecture": "valid main", "lecture_supplement": bad,
            "lecture_revision": "synthetic-v1",
        }, LearningOptions())
    assert retriever.calls == []


def test_supplement_does_not_bypass_other_field_limits_or_stale_revision():
    retriever = RecordingRetriever()
    service = StudyService(FakeProvider(), retriever)
    payload = {"question": "explain", "lecture": "main", "lecture_supplement": "補足。" * 6000,
               "lecture_revision": "synthetic-v1", "other": "大" * 16001}
    with pytest.raises(ValueError, match="入力が長すぎます"):
        service.prepare("dialogue", "Synthetic/Study", "s", payload, LearningOptions())
    with pytest.raises(InvalidResult, match="revisionが古い"):
        service.prepare("dialogue", "Synthetic/Study", "s", {
            "question": "explain", "lecture_supplement": "supplement only", "lecture_revision": "stale",
        }, LearningOptions())
    assert retriever.calls == []


def test_supplement_prompt_and_metadata_survive_quiz_and_grading_without_source_promotion():
    retriever, provider = RecordingRetriever(), FakeProvider()
    service = StudyService(provider, retriever)
    exam = service.execute(service.prepare("quiz", "Synthetic/Study", "s", {
        "topic": "Recall", "lecture": "Recall is a learning method.",
        "lecture_supplement": "Example 2: COOKING_TRANSFER_SENTINEL explains recall by analogy.",
        "lecture_revision": "synthetic-v1",
    }, LearningOptions()))
    prompt = provider.calls[-1]
    data = json.loads(prompt.split("BEGIN_UNTRUSTED_DATA_JSON\n", 1)[1].split("\nEND_UNTRUSTED_DATA_JSON", 1)[0])
    assert "COOKING_TRANSFER_SENTINEL" in data["input"]["lecture_supplement"]
    assert "COOKING_TRANSFER_SENTINEL" not in data["input"]["lecture"]
    assert all("COOKING_TRANSFER_SENTINEL" not in item["text"] for item in data["sources"])
    assert "一般的補足であり教材原文ではない" in prompt
    assert "教材引用や根拠IDの代わりにしてはいけない" in prompt
    assert [item["source_id"] for item in exam["sources"]] == ["S-synthetic"]
    grade = service.execute(service.prepare("grade", "Synthetic/Study", "s",
                                             {"exam": exam, "answer": "Recall first."}, LearningOptions()))
    assert grade["lecture_context"] == exam["lecture_context"]
