from app.models import Requirement
from app.services.search import keywords, render_hits, search
from tests.conftest import FIXTURES


def _files() -> dict[str, str]:
    root = FIXTURES / "repo"
    return {
        p: (root / p).read_text()
        for p in ("src/pages/Login.tsx", "src/api/orders.ts", "src/pages/Dashboard.tsx")
    }


def test_keywords_skip_short_and_common_words() -> None:
    r = Requirement(id="R1", title="Show/hide password toggle", detail="Add it to the form.")
    assert keywords(r) == ["form", "hide", "password", "toggle"]


def test_search_ranks_lines_with_more_words_first() -> None:
    r = Requirement(id="R2", title="Show/hide password toggle", detail="Toggle the password.")
    hits = search(r, _files())
    assert hits[0].path == "src/pages/Login.tsx"
    assert set(hits[0].words) >= {"password"}
    assert all(h.path == "src/pages/Login.tsx" for h in hits)


def test_render_hits_lists_every_requirement() -> None:
    reqs = [
        Requirement(id="R1", title="Date range for orders", detail="Last 7 days by default."),
        Requirement(id="R2", title="Zzz", detail="qqq"),
    ]
    block = render_hits(reqs, _files())
    assert block.startswith("<search_hits>") and block.endswith("</search_hits>")
    assert "src/api/orders.ts:9: const DEFAULT_RANGE_DAYS = 7;" in block
    assert "R2:\n  (no matching lines)" in block
