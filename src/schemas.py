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
SCHEMAS = {
    "answer": TEXT_SCHEMA,
    "lecture": TEXT_SCHEMA,
    "dialogue": TEXT_SCHEMA,
    "trend": TEXT_SCHEMA,
    "curriculum": CURRICULUM_SCHEMA,
    "quiz": QUIZ_SCHEMA,
    "grade": GRADE_SCHEMA,
}


def validate_schema(result: dict, schema: dict) -> None:
    try:
        jsonschema.Draft202012Validator(schema).validate(result)
    except jsonschema.ValidationError as exc:
        # Do not expose the invalid instance (which may contain private text).
        raise InvalidResult("生成結果の形式が不正です。進捗は更新されません。") from exc


def validate_sources(result: dict, sources: list[dict], *, require: bool = False) -> None:
    allowed = {s["source_id"] for s in sources}
    refs = result.get("source_ids", [])
    for field in ("markdown", "supplemental_markdown", "prompt", "model_answer", "rubric", "reason", "improvement"):
        refs = refs + re.findall(r"\[(S-[^\]\s]+)\]", result.get(field, ""))
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
