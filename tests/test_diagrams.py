"""Unicode diagram labels stay readable without widening the supported grammar."""

import pytest

from src.diagrams import mermaid_to_dot


@pytest.mark.parametrize("labels", [
    ("想起練習", "記憶の定着"),
    ("Active recall", "Long-term retention"),
    ("α + β = γ", "Σ x² ≤ ∞"),
])
def test_supported_labels_are_literal_utf8_without_json_unicode_escapes(labels):
    left, right = labels
    original = f'graph TD\nA["{left}"] --> B["{right}"]'
    before = original.encode("utf-8")
    dot = mermaid_to_dot(original)
    assert dot is not None
    assert f'A [label="{left}"];' in dot
    assert f'B [label="{right}"];' in dot
    assert "A -> B;" in dot and "rankdir=TB" in dot
    assert "\\u" not in dot
    assert left.encode("utf-8") in dot.encode("utf-8")
    assert right.encode("utf-8") in dot.encode("utf-8")
    assert original.encode("utf-8") == before


@pytest.mark.parametrize("header,rank", [
    ("graph TD", "TB"), ("graph LR", "LR"), ("flowchart TD", "TB"), ("flowchart LR", "LR"),
])
def test_safe_headers_edges_and_existing_node_labels_remain_supported(header, rank):
    dot = mermaid_to_dot(f'{header}; A["理解"]; A --> B; B["Review"]')
    assert dot is not None
    assert f"rankdir={rank}" in dot
    assert dot.count('A [label="理解"];') == 1
    assert dot.count('B [label="Review"];') == 1
    assert "A -> B;" in dot


@pytest.mark.parametrize("body", [
    'click A "https://example.com"',
    'A["<script>alert(1)</script>"]',
    'A["<b>教材</b>"]',
    'A["https://example.com"]',
    'A["`command`"]',
    'A["\\n"]',
    'A["安全"]; evil [URL="https://example.com"]',
    'A["安全"]; node [image="/tmp/file"]',
    'A["安全"] --> B["unsafe \\" quote"]',
    'style A fill:red',
    'classDef red fill:red',
    'subgraph malicious',
    'A -->|label| B',
    'A --> B --> C',
    'A -.-> B',
    'A["two;statements"]',
    '日本語ID["label"]',
])
def test_unsafe_or_unsupported_syntax_stays_rejected(body):
    assert mermaid_to_dot("graph TD\n" + body) is None


def test_mermaid_directives_are_never_accepted():
    assert mermaid_to_dot('%%{init: {"securityLevel":"loose"}}%%\ngraph TD\nA --> B') is None


@pytest.mark.parametrize("control", [
    "\x00", "\x01", "\t", "\r", "\x1b", "\x7f", "\x85", "\x9f", "\u200b", "\u202e", "\u2066", "\ud800",
])
@pytest.mark.parametrize("position", ["label", "statement"])
def test_controls_in_labels_or_between_statements_are_rejected(control, position):
    text = f'graph TD\nA["日本語{control}English"]' if position == "label" else f'graph TD\n{control}A --> B'
    assert mermaid_to_dot(text) is None


def test_statement_label_and_document_bounds_remain_enforced():
    assert mermaid_to_dot('graph TD\nA["' + "学" * 120 + '"]') is not None
    assert mermaid_to_dot('graph TD\nA["' + "学" * 121 + '"]') is None
    assert mermaid_to_dot("graph TD\n" + "\n".join(f"A{i}" for i in range(40))) is not None
    assert mermaid_to_dot("graph TD\n" + "\n".join(f"A{i}" for i in range(41))) is None
    assert mermaid_to_dot("graph TD\nA" + " " * 8000) is None
    assert mermaid_to_dot("graph TD") is None
    assert mermaid_to_dot("") is None
