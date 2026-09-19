"""Render a deliberately small Mermaid flowchart subset as safe Graphviz data.

No Mermaid directives, clicks, HTML labels, links, CSS or JavaScript are executed.
Unsupported diagrams remain readable code blocks.
"""

import json
import re

NODE = r'([A-Za-z][A-Za-z0-9_]{0,40})(?:\["([^"<>\n]{1,120})"\])?'
EDGE = re.compile(r"^" + NODE + r"\s*-->\s*" + NODE + r"$")
SINGLE = re.compile(r"^" + NODE + r"$")


def mermaid_to_dot(text: str) -> str | None:
    if len(text) > 8000 or any(token in text for token in ("%%", "<", ">", "://", "`", "\\")):
        # Arrows are the only permitted greater-than characters.
        without_arrows = text.replace("-->", "")
        if len(text) > 8000 or any(token in without_arrows for token in ("%%", "<", ">", "://", "`", "\\")):
            return None
    lines = [part.strip() for part in re.split(r"[;\n]", text) if part.strip()]
    if not lines or lines[0] not in ("graph TD", "graph LR", "flowchart TD", "flowchart LR") or len(lines) > 41:
        return None
    rank = "LR" if lines[0].endswith("LR") else "TB"
    nodes: dict[str, str] = {}
    edges = []
    for line in lines[1:]:
        edge = EDGE.fullmatch(line)
        single = SINGLE.fullmatch(line)
        if edge:
            left, label_left, right, label_right = edge.groups()
            nodes[left] = label_left or nodes.get(left, left)
            nodes[right] = label_right or nodes.get(right, right)
            edges.append((left, right))
        elif single:
            name, label = single.groups()
            nodes[name] = label or nodes.get(name, name)
        else:
            return None
    if not nodes:
        return None
    dot = [f"digraph G {{ rankdir={rank}; node [shape=box];"]
    dot.extend(f"{name} [label={json.dumps(label)}];" for name, label in nodes.items())
    dot.extend(f"{left} -> {right};" for left, right in edges)
    return "\n".join(dot + ["}"])
