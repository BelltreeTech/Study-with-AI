"""Synthetic contracts for input-only lectures, sections and unscored practice."""

import copy
import json
from dataclasses import asdict

import pytest

from src.config import PROMPT_VERSION, SCHEMA_VERSION, LearningOptions
from src.lecture_context import select_edition_context
from src.schemas import (
    SCHEMAS,
    InvalidResult,
    validate_lecture_plan,
    validate_lecture_section,
    validate_practice_set,
)
from src.service import TASKS, LearningRequest, StudyService

SOURCE = {"source_id": "S-synthetic", "source_file": "Synthetic/Study/book.pdf", "page_number": 1,
          "chunk_id": "chunk", "text": "Synthetic concepts and worked examples."}


def plan(count=2, *, code=False, math=False):
    coverage = ["prerequisites", "concepts", "worked_example", "pitfalls", "summary"]
    if code:
        coverage.append("implementation")
    if math:
        coverage.append("derivation")
    return {"title": "Synthetic course", "objectives": ["Understand the mechanism"], "prerequisites": [],
            "requires_code": code, "requires_math": math,
            "sections": [{"section_id": f"s{i + 1}", "title": f"Topic {i + 1}",
                          "objectives": [f"Explain objective {i + 1}"], "topics": [f"concept{i + 1}"],
                          "coverage": coverage if i == 0 else ["concepts"]} for i in range(count)],
            "source_ids": ["S-synthetic"]}


def section_result(section):
    return {"section_id": section["section_id"], "markdown": f"Explanation for {section['section_id']} [S-synthetic]",
            "summary": "The mechanism follows the assumptions.", "covered_objectives": section["objectives"],
            "supplemental_markdown": "General illustrative example.", "insufficient_evidence": False,
            "source_ids": ["S-synthetic"]}


def practice():
    return {"title": "Self practice", "questions": [
        {"id": f"q{i}", "kind": kind, "prompt": "Explain the mechanism.", "learning_objective": "Explain objective 1",
         "hints": ["Start with the definition."], "answer": "The relation follows the assumptions.",
         "explanation": "Because of the definition.", "criteria": ["Names the assumptions."],
         "source_ids": ["S-synthetic"]} for i, kind in enumerate(("concept", "application", "calculation"), 1)
    ]}


class Retriever:
    def __init__(self):
        self.current = "revision-1"
        self.calls = []

    def revision(self, subject):
        return self.current

    def search(self, subject, query, top_k=5):
        self.calls.append((subject, query, top_k))
        return [dict(SOURCE)]


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate(self, prompt, schema, cancel_event=None):
        self.calls.append(prompt)
        return copy.deepcopy(self.result)


def service(result):
    provider, retriever = Provider(result), Retriever()
    return StudyService(provider, retriever), provider, retriever


def set_payload():
    return {"topic": "Synthetic concepts", "lecture_id": "lecture-1", "lecture_revision": "revision-1",
            "chapter_index": 0, "plan": plan()}


def saved_practice():
    svc, _, _ = service(practice())
    return svc.execute(svc.prepare("practice_set", "Synthetic/Study", "session", set_payload(),
                                   LearningOptions(), course_id="course", request_id="practice-1"))


def feedback_payload():
    return {"practice": saved_practice(), "question_id": "q1", "answer": "The assumptions define the relation.",
            "lecture_id": "lecture-1", "lecture_revision": "revision-1", "chapter_index": 0}


def feedback():
    return {"question_id": "q1", "strengths": ["Identifies the assumptions"], "misconceptions": [],
            "next_steps": ["Apply it to an example"], "review_topics": [], "source_ids": ["S-synthetic"]}


def test_time_scope_defaults_saved_legacy_and_explicit_setting():
    assert LearningOptions().time_scope == LearningOptions.from_saved({}).time_scope == "lecture_input"
    assert LearningOptions.from_saved({"session_minutes": 45}).time_scope == "legacy_total"
    assert LearningOptions.from_saved({"session_minutes": 45, "time_scope": "lecture_input"}).time_scope == "lecture_input"
    with pytest.raises(ValueError):
        LearningOptions(time_scope="all-time")
    svc, _, _ = service(plan())
    request = svc.prepare("lecture_plan", "Synthetic/Study", "session", {"title": "Topic"}, LearningOptions())
    stored = request.to_dict()
    assert LearningRequest.from_dict(stored).digest() == request.digest()
    stored["options"].pop("time_scope")
    assert LearningRequest.from_dict(stored).options.time_scope == "legacy_total"
    assert (PROMPT_VERSION, SCHEMA_VERSION) == ("study-4", "study-3")


def test_time_prompts_separate_input_from_self_practice():
    for instruction in TASKS.values():
        assert "読む・練習する・思い出す時間を配分" not in instruction
        assert "session_minutes内でできる復習" not in instruction
    assert "自己演習・相談・試験は別" in TASKS["lecture"]
    svc, provider, _ = service(plan())
    result = svc.execute(svc.prepare("lecture_plan", "Synthetic/Study", "s", {"title": "Concepts"}, LearningOptions()))
    assert result["learning_options"]["time_scope"] == "lecture_input"
    assert "session_minutesは講義の説明を読む時間だけ" in provider.calls[0]
    assert "insufficient_evidence=true" not in provider.calls[0]
    assert "supplemental_markdownへ" not in provider.calls[0]


@pytest.mark.parametrize("change", ["missing-summary", "nonsequential", "math", "code"])
def test_invalid_coverage_or_section_order_is_rejected(change):
    result = plan()
    if change == "missing-summary":
        result["sections"][0]["coverage"].remove("summary")
    elif change == "nonsequential":
        result["sections"][1]["section_id"] = "s3"
    else:
        result["requires_" + change] = True
    with pytest.raises(InvalidResult):
        validate_lecture_plan(result, [SOURCE])
    validate_lecture_plan(plan(code=True, math=True), [SOURCE])


def test_section_request_uses_exact_plan_section_topics_and_bounded_prior_summary():
    lesson_plan = plan()
    section = lesson_plan["sections"][1]
    svc, provider, retriever = service(section_result(section))
    request = svc.prepare("lecture_section", "Synthetic/Study", "session", {
        "plan": {**lesson_plan, "sources": [SOURCE], "model": "gpt-6-astra"}, "section": section,
        "prior_summaries": [{"section_id": "s1", "summary": "Earlier concepts"}],
    }, LearningOptions())
    assert retriever.calls == [("Synthetic/Study", "Topic 2\nconcept2", 5)]
    assert request.payload["plan"] == lesson_plan
    result = svc.execute(request)
    assert result["section_id"] == "s2" and result["covered_objectives"] == section["objectives"]
    assert "Earlier concepts" in provider.calls[-1]


@pytest.mark.parametrize("summaries", [
    [{"section_id": "s2", "summary": "future"}],
    [{"section_id": "s1", "summary": "x"}] * 2,
    [{"section_id": "s1", "summary": "x" * 601}],
], ids=["future", "duplicate", "too-long"])
def test_invalid_prior_summaries_fail_before_retrieval(summaries):
    svc, provider, retriever = service({})
    with pytest.raises(InvalidResult):
        svc.prepare("lecture_section", "Synthetic/Study", "s", {
            "plan": plan(), "section": plan()["sections"][1], "prior_summaries": summaries,
        }, LearningOptions())
    assert not provider.calls and not retriever.calls


@pytest.mark.parametrize("field,value", [("section_id", "s2"), ("covered_objectives", ["Other objective"])])
def test_section_result_must_match_requested_id_and_objectives(field, value):
    section = plan()["sections"][0]
    result = section_result(section) | {field: value}
    with pytest.raises(InvalidResult):
        validate_lecture_section(result, section, [SOURCE])


@pytest.mark.parametrize("change", ["two", "duplicate", "no-concept", "code", "invented-hint-source"])
def test_practice_composition_and_sources_are_strict(change):
    result = practice()
    if change == "two":
        result["questions"].pop()
    elif change == "duplicate":
        result["questions"][1]["id"] = "q1"
    elif change == "no-concept":
        result["questions"][0]["kind"] = "application"
    elif change == "code":
        result["questions"][1]["kind"] = "code"
    else:
        result["questions"][0]["hints"] = ["Use [S-invented]"]
    with pytest.raises(InvalidResult):
        validate_practice_set(result, [SOURCE], requires_code=False)


def test_practice_metadata_and_feedback_have_no_grade_fields():
    payload = feedback_payload()
    payload["practice"]["lecture_context"] = {"is_excerpt": True, "selection_method": "edition_excerpts"}
    svc, _, _ = service(feedback())
    result = svc.execute(svc.prepare("practice_feedback", "Synthetic/Study", "session", payload,
                                     LearningOptions(), course_id="course"))
    assert result["practice_id"] == "practice-1" and result["lecture_id"] == "lecture-1"
    assert not {"score", "passed", "pass_line", "xp"} & result.keys()
    assert payload["practice"]["requires_code"] is False
    assert payload["practice"]["learning_options"] == asdict(LearningOptions())
    assert result["lecture_context"] == payload["practice"]["lecture_context"]


@pytest.mark.parametrize("key,value", [("subject", "Other/Subject"), ("session_id", "other"), ("course_id", "other"),
                                      ("lecture_id", "older"), ("chapter_index", 1), ("material_revision", "old"),
                                      ("practice_id", "")])
def test_feedback_rejects_wrong_snapshot_scope_or_revision(key, value):
    payload = feedback_payload()
    payload["practice"][key] = value
    svc, provider, _ = service(feedback())
    with pytest.raises(InvalidResult):
        svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    assert not provider.calls


@pytest.mark.parametrize("result", [feedback() | {"question_id": "q2"}, feedback() | {"score": 100}])
def test_feedback_rejects_wrong_question_or_score_output(result):
    svc, _, _ = service(result)
    with pytest.raises(InvalidResult):
        svc.execute(svc.prepare("practice_feedback", "Synthetic/Study", "session", feedback_payload(),
                                LearningOptions(), course_id="course"))


def edition(count=8):
    lesson_plan = plan(count)
    sections = []
    for section in lesson_plan["sections"]:
        result = section_result(section)
        result["markdown"] = f"MAIN_{section['section_id']}\n" + ("Definition and detailed worked example.\n\n" * 250)
        result["supplemental_markdown"] = f"SUPPLEMENT_{section['section_id']}\n" + ("General analogy.\n\n" * 200)
        sections.append(result | {"sources": [SOURCE], "material_revision": "revision-1"})
    return {"format": "sections-v1", "lecture_id": "edition-1", "material_revision": "revision-1",
            "plan": lesson_plan, "sections": sections}


def test_edition_context_distributes_all_sections_and_keeps_source_distinction():
    saved = edition()
    original = copy.deepcopy(saved)
    result = select_edition_context(saved)
    assert len(result["lecture"]) + len(result["lecture_supplement"]) <= 6000
    assert result["lecture_revision"] == "revision-1" and result["lecture_context_mode"] == "edition_excerpts"
    for i in range(1, 9):
        assert f"MAIN_s{i}" in result["lecture"]
        assert f"Explain objective {i}" in result["lecture"]
        assert f"SUPPLEMENT_s{i}" in result["lecture_supplement"]
    assert "教材原文ではありません" in result["lecture_supplement"]
    assert "sources" not in result and saved == original
    selected = select_edition_context(saved, "s8")
    assert "MAIN_s8" in selected["lecture"] and "MAIN_s1" not in selected["lecture"]
    assert len(selected["lecture"]) + len(selected["lecture_supplement"]) <= 6000


def test_edition_rejects_missing_or_stale_sections_and_supports_legacy():
    saved = edition()
    saved["sections"][3]["material_revision"] = "old"
    with pytest.raises(InvalidResult):
        select_edition_context(saved)
    saved = edition()
    saved["sections"].pop()
    with pytest.raises(InvalidResult):
        select_edition_context(saved)
    old = {"markdown": "Saved lecture", "supplemental_markdown": "Example", "material_revision": "revision-1"}
    assert "Saved lecture" in select_edition_context(old)["lecture"]
    with pytest.raises(InvalidResult):
        select_edition_context(old, "s1")


def test_edition_payload_survives_service_selection_as_explicit_excerpt():
    svc, provider, _ = service({"markdown": "Answer", "supplemental_markdown": "", "insufficient_evidence": False,
                              "source_ids": ["S-synthetic"]})
    payload = {"question": "Explain the chapter", **select_edition_context(edition())}
    result = svc.execute(svc.prepare("dialogue", "Synthetic/Study", "s", payload, LearningOptions()))
    assert result["lecture_context"]["is_excerpt"]
    assert "全文を確認したと主張しない" in provider.calls[-1]


def test_total_prompt_budget_rejects_before_provider_call():
    svc, provider, _ = service(plan())
    request = svc.prepare("lecture_plan", "Synthetic/Study", "s", {"title": "Topic"}, LearningOptions())
    request.payload["oversized-after-prepare"] = "大" * 24000
    with pytest.raises(ValueError, match="生成への入力が上限"):
        svc.execute(request)
    assert provider.calls == []
    assert json.dumps(SCHEMAS["practice_feedback"]).find('"score"') < 0


def maximum_practice_payload():
    payload = feedback_payload()
    snapshot = payload["practice"]
    snapshot["title"] = "題" * 500
    for question in snapshot["questions"]:
        question.update(prompt="問" * 600, learning_objective="目" * 160,
                        hints=["ヒ" * 159 + str(i) for i in range(3)], answer="答" * 1000,
                        explanation="説" * 1000, criteria=["基" * 119 + str(i) for i in range(4)])
    snapshot["sources"] = [{**SOURCE, "source_id": "S-synthetic" if i == 0 else f"S-other-{i}",
                             "text": "教" * 1000} for i in range(10)]
    return payload


def test_large_valid_practice_snapshot_projects_to_answered_question_before_input_limit():
    payload = maximum_practice_payload()
    original = copy.deepcopy(payload)
    assert len(json.dumps(payload, ensure_ascii=False).encode()) > 48000
    svc, provider, _ = service(feedback())
    request = svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    assert len(request.payload["practice"]["questions"]) == 1
    assert request.payload["practice"]["questions"][0]["id"] == "q1"
    assert [s["source_id"] for s in request.payload["practice"]["sources"]] == ["S-synthetic"]
    assert len(json.dumps(request.payload, ensure_ascii=False).encode()) < 48000
    assert svc.execute(request)["question_id"] == "q1"
    assert len(provider.calls[0].encode()) < 65536
    assert payload == original


def test_projection_validates_other_questions_and_retains_limits_on_unknown_metadata_and_answer():
    payload = maximum_practice_payload()
    payload["practice"]["questions"][2]["source_ids"] = ["S-invented"]
    svc, provider, _ = service(feedback())
    with pytest.raises(InvalidResult):
        svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    for field in ("answer", "metadata"):
        payload = maximum_practice_payload()
        if field == "answer":
            payload["answer"] = "大" * 16001
        else:
            payload["practice"]["unknown_metadata"] = "大" * 16001
        with pytest.raises(ValueError, match="入力が長すぎます"):
            svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    assert not provider.calls


def test_projection_preserves_inline_references_in_hints():
    payload = feedback_payload()
    payload["practice"]["sources"].append({**SOURCE, "source_id": "S-secondary"})
    payload["practice"]["questions"][0]["hints"] = ["Compare [S-secondary]."]
    svc, _, _ = service(feedback())
    request = svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    assert {s["source_id"] for s in request.sources} == {"S-synthetic", "S-secondary"}


def test_feedback_referencing_all_ten_sources_transmits_evidence_once():
    payload = maximum_practice_payload()
    refs = [s["source_id"] for s in payload["practice"]["sources"]]
    for question in payload["practice"]["questions"]:
        question["source_ids"] = refs
    original = copy.deepcopy(payload)
    svc, provider, _ = service(feedback())
    request = svc.prepare("practice_feedback", "Synthetic/Study", "session", payload, LearningOptions(), course_id="course")
    saved = copy.deepcopy(request.payload)
    svc.execute(request)
    data = json.loads(provider.calls[-1].split("BEGIN_UNTRUSTED_DATA_JSON\n")[1].split("\nEND_UNTRUSTED_DATA_JSON")[0])
    assert len(data["sources"]) == 10
    assert "sources" not in data["input"]["practice"]
    assert len(provider.calls[-1].encode()) <= 65536
    assert request.payload == saved and payload == original
