"""Local search over the files that were fetched. No code host search API is used.

For each requirement, find the lines that mention its words, ranked by how many different
words a line contains. The hits go to the compare step as pointers, so the model looks at the
right lines in large files; they are not evidence by themselves.
"""

import re
from dataclasses import dataclass

from app.models import Requirement

MAX_HITS_PER_REQUIREMENT = 8
MAX_LINE_CHARS = 160
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOPWORDS = frozenset(
    """
    about above after again also always and any are because been before being below between
    both but can cannot could did does doing done down during each else even every few for
    from further had has have having here how into its just keep like make many may more most
    much must need needs next not now off once only other our out over own same should show
    shown some still such than that the their them then there these they this those through
    too under until use used user users using very want was way were what when where which
    while who why will with within without would yes you your add adds added new page screen
    button field click instead exactly already today default stays
    """.split()
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    text: str
    words: tuple[str, ...]


def keywords(requirement: Requirement) -> list[str]:
    text = " ".join(
        part for part in (requirement.title, requirement.detail, requirement.source_quote) if part
    )
    words = {w.lower() for w in _WORD.findall(text)}
    return sorted(w for w in words if len(w) >= 4 and w not in _STOPWORDS)


def search(requirement: Requirement, files: dict[str, str]) -> list[Hit]:
    words = keywords(requirement)
    if not words:
        return []
    hits: list[Hit] = []
    for path, text in files.items():
        for number, line in enumerate(text.split("\n"), start=1):
            lower = line.lower()
            found = tuple(w for w in words if w in lower)
            if found:
                hits.append(Hit(path, number, line.strip()[:MAX_LINE_CHARS], found))
    hits.sort(key=lambda h: (-len(h.words), h.path, h.line))
    return hits[:MAX_HITS_PER_REQUIREMENT]


def render_hits(requirements: list[Requirement], files: dict[str, str]) -> str:
    """The `<search_hits>` block for the compare prompt."""
    sections = []
    for r in requirements:
        hits = search(r, files)
        lines = [f"{h.path}:{h.line}: {h.text}" for h in hits] or ["(no matching lines)"]
        sections.append(f"{r.id}:\n" + "\n".join(f"  {line}" for line in lines))
    return "<search_hits>\n" + "\n".join(sections) + "\n</search_hits>"
