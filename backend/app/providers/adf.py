"""Plain text -> Atlassian Document Format (ADF), as Jira Cloud v3 requires for descriptions.

Rules, kept deliberately small:
- blocks are separated by blank lines;
- consecutive lines starting with "- " or "* " become a bullet list;
- a line ending with ":" directly before a list is bold (e.g. "Acceptance criteria:");
- other lines in a block become one paragraph, joined with hard breaks.
Text is never interpreted as markup, so nothing in a draft can inject ADF nodes.
"""

import re
from typing import Any

Node = dict[str, Any]

_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")


def to_adf(text: str) -> Node:
    content: list[Node] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        content.extend(_block(block.split("\n")))
    return {"type": "doc", "version": 1, "content": content or [_paragraph([])]}


def _block(lines: list[str]) -> list[Node]:
    nodes: list[Node] = []
    text_lines: list[str] = []
    items: list[str] = []

    def flush_text(bold_last: bool = False) -> None:
        if text_lines:
            nodes.append(_paragraph(text_lines, bold_last=bold_last))
            text_lines.clear()

    def flush_items() -> None:
        if items:
            nodes.append(
                {
                    "type": "bulletList",
                    "content": [
                        {"type": "listItem", "content": [_paragraph([item])]} for item in items
                    ],
                }
            )
            items.clear()

    for line in lines:
        match = _BULLET.match(line)
        if match:
            flush_text(bold_last=bool(text_lines) and text_lines[-1].rstrip().endswith(":"))
            items.append(match.group(1).strip())
        else:
            flush_items()
            if line.strip():
                text_lines.append(line.strip())
    flush_items()
    flush_text()
    return nodes


def _paragraph(lines: list[str], bold_last: bool = False) -> Node:
    content: list[Node] = []
    for i, line in enumerate(lines):
        if i:
            content.append({"type": "hardBreak"})
        node: Node = {"type": "text", "text": line}
        if bold_last and i == len(lines) - 1:
            node["marks"] = [{"type": "strong"}]
        if line:
            content.append(node)
    return {"type": "paragraph", "content": content}
