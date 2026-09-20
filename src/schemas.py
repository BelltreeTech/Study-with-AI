"""Strict generated-output contracts plus deterministic learning rules."""

import re
from typing import Any, TypedDict

import jsonschema

from src.config import PASS_SCORES


class InvalidResult(ValueError):
    code = "invalid_result"


class TextResult(TypedDict):
    markdown: str
    source_ids: list[str]
    supplemental_markdown: str
    insufficient_evidence: bool


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 40000}
SHORT = {"type": "string", "minLength": 1, "maxLength": 500}
IDS = {"type": "array", "items": {"type": "string"}, "maxItems": 10, "uniqueItems": True}
TEXT_SCHEMA = obj(
    {
        "markdown": TEXT,
        "source_ids": IDS,
        "supplemental_markdown": {"type": "string", "maxLength": 20000},
        "insufficient_evidence": {"type": "boolean"},
    }
)
CHAPTER = obj(
    {
        "chapter": {"type": "integer", "minimum": 1, "maximum": 15},
        "title": SHORT,
        "description": {"type": "string", "minLength": 1, "maxLength": 2000},
    }
)
CURRICULUM_SCHEMA = obj(
    {"chapters": {"type": "array", "items": CHAPTER, "minItems": 1, "maxItems": 15}, "source_ids": IDS}
)
QUESTION = obj(
    {
        "id": SHORT,
        "prompt": TEXT,
        "max_points": {"type": "integer", "minimum": 1, "maximum": 100},
        "rubric": TEXT,
        "model_answer": TEXT,
        "source_ids": IDS,
    }
)
QUIZ_SCHEMA = obj({"title": SHORT, "questions": {"type": "array", "items": QUESTION, "minItems": 1, "maxItems": 20}})
GRADE_ITEM = obj(
    {
        "question_id": SHORT,
        "points": {"type": "integer", "minimum": 0, "maximum": 100},
        "max_points": {"type": "integer", "minimum": 1, "maximum": 100},
        "reason": TEXT,
        "improvement": TEXT,
        "source_ids": IDS,
    }
)
GRADE_SCHEMA = obj(
    {
        "items": {"type": "array", "items": GRADE_ITEM, "minItems": 1, "maxItems": 20},
        "feedback": TEXT,
        "weaknesses": {"type": "array", "items": SHORT, "maxItems": 3, "uniqueItems": True},
    }
)


def strings(maximum: int, count: int = 4, minimum: int = 1) -> dict:
    return {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": maximum},
            "minItems": minimum, "maxItems": count, "uniqueItems": True}


COVERAGE = ("prerequisites", "concepts", "derivation", "worked_example", "implementation", "pitfalls", "summary")
PLAN_SECTION = obj({
    "section_id": {"type": "string", "pattern": "^s[1-8]$"},
    "title": {"type": "string", "minLength": 1, "maxLength": 80},
    "objectives": strings(100, 3), "topics": strings(80, 3),
    "coverage": {"type": "array", "items": {"type": "string", "enum": list(COVERAGE)},
                 "minItems": 1, "maxItems": 7, "uniqueItems": True},
})
LECTURE_PLAN_SCHEMA = obj({
    "title": {"type": "string", "minLength": 1, "maxLength": 120},
    "objectives": strings(120), "prerequisites": strings(120, minimum=0),
    "requires_code": {"type": "boolean"}, "requires_math": {"type": "boolean"},
    "sections": {"type": "array", "items": PLAN_SECTION, "minItems": 1, "maxItems": 8}, "source_ids": IDS,
})
LECTURE_SECTION_SCHEMA = obj({
    **TEXT_SCHEMA["properties"], "section_id": {"type": "string", "pattern": "^s[1-8]$"},
    "summary": {"type": "string", "minLength": 1, "maxLength": 600},
    "covered_objectives": strings(100, 3),
})
PRACTICE_QUESTION = obj({
    "id": {"type": "string", "minLength": 1, "maxLength": 40},
    "kind": {"type": "string", "enum": ["concept", "application", "calculation", "code"]},
    "prompt": {"type": "string", "minLength": 1, "maxLength": 600},
    "learning_objective": {"type": "string", "minLength": 1, "maxLength": 160},
    "hints": strings(160, 3),
    "answer": {"type": "string", "minLength": 1, "maxLength": 1000},
    "explanation": {"type": "string", "minLength": 1, "maxLength": 1000},
    "criteria": strings(120), "source_ids": IDS,
})
PRACTICE_SET_SCHEMA = obj({"title": SHORT, "questions": {
    "type": "array", "items": PRACTICE_QUESTION, "minItems": 3, "maxItems": 3,
}})
PRACTICE_FEEDBACK_SCHEMA = obj({
    "question_id": {"type": "string", "minLength": 1, "maxLength": 40},
    "strengths": strings(300, minimum=0), "misconceptions": strings(300, minimum=0),
    "next_steps": strings(300), "review_topics": strings(160, minimum=0), "source_ids": IDS,
})
SCHEMAS = {
    "answer": TEXT_SCHEMA,
    "lecture": TEXT_SCHEMA,
    "dialogue": TEXT_SCHEMA,
    "trend": TEXT_SCHEMA,
    "curriculum": CURRICULUM_SCHEMA,
    "quiz": QUIZ_SCHEMA,
    "grade": GRADE_SCHEMA,
    "lecture_plan": LECTURE_PLAN_SCHEMA, "lecture_section": LECTURE_SECTION_SCHEMA,
    "practice_set": PRACTICE_SET_SCHEMA, "practice_feedback": PRACTICE_FEEDBACK_SCHEMA,
}


def validate_schema(result: dict, schema: dict) -> None:
    try:
        jsonschema.Draft202012Validator(schema).validate(result)
    except jsonschema.ValidationError as exc:
        # Do not expose the invalid instance (which may contain private text).
        raise InvalidResult("生成結果の形式が不正です。進捗は更新されません。") from exc


def validate_sources(result: dict, sources: list[dict], *, require: bool = False) -> None:
    if not isinstance(sources, list) or any(not isinstance(s, dict) or not isinstance(s.get("source_id"), str)
                                            or not s["source_id"] for s in sources):
        raise InvalidResult("教材根拠の形式が不正です。")
    allowed = {s["source_id"] for s in sources}
    refs = result.get("source_ids", [])

    def inline_refs(value: Any) -> list[str]:
        if isinstance(value, str):
            return re.findall(r"\[(S-[^\]\s]+)\]", value)
        if isinstance(value, list):
            return [ref for item in value for ref in inline_refs(item)]
        if isinstance(value, dict):
            return [ref for item in value.values() for ref in inline_refs(item)]
        return []

    refs = refs + inline_refs(result)
    if set(refs) - allowed:
        raise InvalidResult("提供していない教材への参照があります。")
    if require and not refs:
        raise InvalidResult("教材由来の説明に根拠IDがありません。")


def validate_quiz(result: dict, sources: list[dict], *, expected_points: list[int] | None = None) -> None:
    validate_schema(result, QUIZ_SCHEMA)
    questions = result["questions"]
    if len({q["id"] for q in questions}) != len(questions):
        raise InvalidResult("問題IDが重複しています。")
    if sum(q["max_points"] for q in questions) != 100:
        raise InvalidResult("問題の配点合計が100点ではありません。")
    if expected_points is not None and [q["max_points"] for q in questions] != expected_points:
        raise InvalidResult("選択した難易度の問題数・配点と一致しません。")
    for question in questions:
        validate_sources(question, sources, require=True)


def validate_lecture_plan(result: dict, sources: list[dict] | None = None) -> None:
    validate_schema(result, LECTURE_PLAN_SCHEMA)
    sections = result["sections"]
    if [section["section_id"] for section in sections] != [f"s{i + 1}" for i in range(len(sections))]:
        raise InvalidResult("講義計画の節IDはs1から連続する必要があります。")
    covered = {tag for section in sections for tag in section["coverage"]}
    required = {"prerequisites", "concepts", "worked_example", "pitfalls", "summary"}
    if result["requires_math"]:
        required.add("derivation")
    if result["requires_code"]:
        required.add("implementation")
    if not required <= covered:
        raise InvalidResult("講義計画に必要な内容が不足しています。")
    if sources is not None:
        validate_sources(result, sources, require=True)


def validate_lecture_section(result: dict, section: dict, sources: list[dict] | None = None) -> None:
    validate_schema(result, LECTURE_SECTION_SCHEMA)
    if result["section_id"] != section["section_id"] or result["covered_objectives"] != section["objectives"]:
        raise InvalidResult("生成した講義節と要求した節・到達目標が一致しません。")
    if sources is not None:
        validate_sources(result, sources, require=not result["insufficient_evidence"])


def validate_practice_set(result: dict, sources: list[dict], *, requires_code: bool) -> None:
    validate_schema(result, PRACTICE_SET_SCHEMA)
    questions = result["questions"]
    if len({question["id"] for question in questions}) != 3 or not any(q["kind"] == "concept" for q in questions):
        raise InvalidResult("練習は一意なIDを持つ3問で、概念の確認を含む必要があります。")
    if not requires_code and any(q["kind"] == "code" for q in questions):
        raise InvalidResult("コード不要の講義にコード練習を追加できません。")
    for question in questions:
        validate_sources(question, sources, require=True)


def validate_practice_feedback(result: dict, question_id: str, sources: list[dict]) -> None:
    validate_schema(result, PRACTICE_FEEDBACK_SCHEMA)
    if result["question_id"] != question_id:
        raise InvalidResult("フィードバック対象の練習問題が一致しません。")
    validate_sources(result, sources, require=True)


def grade_total(result: dict, exam: dict) -> dict[str, Any]:
    """Never accept model-reported totals, pass flags, or score-like prose."""
    validate_schema(result, GRADE_SCHEMA)
    validate_quiz({"title": exam["title"], "questions": exam["questions"]}, exam["sources"])
    expected = {q["id"]: q["max_points"] for q in exam["questions"]}
    items = result["items"]
    if len(items) != len(expected) or {x["question_id"] for x in items} != set(expected):
        raise InvalidResult("設問別採点に重複・欠落があります。")
    for item in items:
        if item["max_points"] != expected[item["question_id"]] or item["points"] > item["max_points"]:
            raise InvalidResult("設問別得点が配点範囲と一致しません。")
        validate_sources(item, exam["sources"], require=True)
    score = sum(x["points"] for x in items)
    threshold = PASS_SCORES[exam["difficulty"]]
    return {**result, "score": score, "pass_line": threshold, "passed": score >= threshold}


def public_exam(exam: dict) -> dict:
    """Only this projection is rendered before submission; no rubric or answer fields."""
    return {
        "title": exam["title"],
        "questions": [{"id": q["id"], "prompt": q["prompt"], "max_points": q["max_points"]} for q in exam["questions"]],
    }
