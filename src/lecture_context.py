"""Select bounded, attributable excerpts from a saved lecture without generation."""

from __future__ import annotations

import math
import re
from collections import Counter

LECTURE_MAX_CHARS = 40000
LECTURE_SUPPLEMENT_MAX_CHARS = 20000
LECTURE_CONTEXT_CHARS = 6000


def _terms(text: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9_]{2,}", text.casefold()))
    for run in re.findall(r"[一-龯ぁ-んァ-ンー]+", text):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def _spans(text: str, chunk_chars: int = 1000) -> list[tuple[int, int]]:
    """Prefer paragraph/sentence boundaries, splitting only oversized paragraphs."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            minimum = min(400, chunk_chars // 2)
            region = text[start + minimum:end]
            for delimiter in ("\n\n", "\n", "。", ". ", "！", "？"):
                offset = region.rfind(delimiter)
                if offset >= 0:
                    end = start + minimum + offset + len(delimiter)
                    break
            # Keep a nearby citation intact if the fallback cut reaches inside it.
            bracket = text.rfind("[S-", max(start + 1, end - 80), end)
            if bracket >= 0 and "]" not in text[bracket:end]:
                end = bracket
        spans.append((start, end))
        start = end
    return spans


def select_lecture_context(text: str, query: str = "") -> tuple[str, dict]:
    """Keep the start, ending, relevant passages and spread across other sections.

    Ranges use original zero-based offsets with an exclusive end. selected_chars
    counts original text; context_chars additionally counts explicit range labels.
    This is excerpt selection, not a generated summary or a coverage guarantee.
    """
    if not isinstance(text, str) or len(text) > LECTURE_MAX_CHARS:
        raise ValueError("保存講義は40000文字以内の文章である必要があります。")
    return _select(text, query, LECTURE_CONTEXT_CHARS)


def _select(text: str, query: str, budget: int) -> tuple[str, dict]:
    if len(text) <= budget:
        ranges = [{"start": 0, "end": len(text), "reason": "complete"}] if text else []
        return text, {
            "total_chars": len(text), "selected_chars": len(text), "context_chars": len(text),
            "is_excerpt": False, "ranges": ranges, "selection_method": "lecture_excerpt_v1",
        }
    spans = _spans(text, min(1000, max(300, budget // 4)))
    query_terms = _terms(query[:2400])
    matches = [_terms(text[start:end]) & query_terms for start, end in spans]
    frequency = Counter(term for terms in matches for term in terms)
    scores = [sum(math.log(1 + len(spans) / frequency[term]) for term in terms) for terms in matches]
    chosen: dict[int, str] = {}
    used = 0

    def block(i: int) -> str:
        start, end = spans[i]
        return f"[講義原文 {start + 1}〜{end}文字]\n{text[start:end]}"

    def add(i: int, reason: str) -> bool:
        nonlocal used
        cost = len(block(i)) + (2 if chosen else 0)
        if i in chosen or used + cost > budget:
            return False
        chosen[i] = reason
        used += cost
        return True

    add(0, "opening")
    add(len(spans) - 1, "ending")
    ranked = sorted(range(len(spans)), key=lambda i: (-scores[i], i))
    # Reserve room for structural breadth; at most two extra matching passages.
    for i in [i for i in ranked if scores[i] > 0 and i not in chosen][:2]:
        add(i, "query_relevance")
    remaining = set(range(len(spans))) - chosen.keys()
    while remaining:
        i = max(remaining, key=lambda i: (min(abs(i - other) for other in chosen), scores[i], -i))
        add(i, "section_spread")
        remaining.remove(i)
    order = sorted(chosen)
    result = "\n\n".join(block(i) for i in order)
    ranges = [{"start": spans[i][0], "end": spans[i][1], "reason": chosen[i]} for i in order]
    return result, {
        "total_chars": len(text), "selected_chars": sum(end - start for start, end in (spans[i] for i in order)),
        "context_chars": len(result), "is_excerpt": True, "ranges": ranges,
        "selection_method": "lecture_excerpt_v1",
    }


def select_lecture_material(text: str, supplement: str = "", query: str = "") -> tuple[str, str, dict]:
    """Share one context budget while retaining the main/supplement distinction.

    Both fields are saved generated content. Supplemental explanations are never
    promoted to material quotations or given new source IDs by this selector.
    """
    if not isinstance(text, str) or len(text) > LECTURE_MAX_CHARS:
        raise ValueError("保存講義は40000文字以内の文章である必要があります。")
    if not isinstance(supplement, str) or len(supplement) > LECTURE_SUPPLEMENT_MAX_CHARS:
        raise ValueError("保存講義の一般的補足は20000文字以内の文章である必要があります。")
    if not supplement:
        selected, context = select_lecture_context(text, query)
        return selected, "", context
    headers = {
        "lecture": "[講義本文]\n" if text else "",
        "lecture_supplement": "[一般的補足（教材原文ではありません）]\n",
    }
    available = LECTURE_CONTEXT_CHARS - sum(map(len, headers.values()))
    half = available // 2
    query_terms = _terms(query[:2400])
    main_match = len(_terms(text) & query_terms)
    supplement_match = len(_terms(supplement) & query_terms)
    # Each substantial field keeps at least a third of the budget. Give more
    # space to the field matching the learner's question; transfer unused room.
    main_target = (available * 2 // 3 if main_match > supplement_match else
                   available // 3 if supplement_match > main_match else half)
    main_budget = min(len(text), main_target)
    supplement_budget = min(len(supplement), available - main_budget)
    main_budget = min(len(text), available - supplement_budget)
    selected_main, main_context = _select(text, query, main_budget)
    selected_supplement, supplement_context = _select(supplement, query, supplement_budget)
    selected_main = headers["lecture"] + selected_main
    selected_supplement = headers["lecture_supplement"] + selected_supplement
    sections = {
        "lecture": {**main_context, "context_chars": len(selected_main), "content_kind": "lecture_main"},
        "lecture_supplement": {**supplement_context, "context_chars": len(selected_supplement),
                               "content_kind": "general_supplement_not_material"},
    }
    context = {
        "total_chars": len(text) + len(supplement),
        "selected_chars": main_context["selected_chars"] + supplement_context["selected_chars"],
        "context_chars": len(selected_main) + len(selected_supplement),
        "is_excerpt": main_context["is_excerpt"] or supplement_context["is_excerpt"],
        "ranges": [{**item, "field": field} for field, section in sections.items() for item in section["ranges"]],
        "sections": sections, "selection_method": "lecture_and_supplement_excerpt_v2",
    }
    return selected_main, selected_supplement, context
