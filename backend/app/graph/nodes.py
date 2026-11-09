"""Pipeline nodes. Each takes the state and returns a partial update.

Providers and the LLM come from `Deps`, built from settings outside the graph, so no
credentials end up in checkpointed state. LLM output is checked by code before it is kept:
invented file paths and line numbers are dropped, and claims without evidence are
downgraded to "unclear".
"""

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from app.config import Settings
from app.db import Database
from app.graph.state import RunState
from app.llm import LLM, Image, Part, Text
from app.models import (
    CodeFinding,
    CodePlan,
    DraftList,
    Evidence,
    FindingList,
    MeetingAnalysis,
    Requirement,
    RequirementList,
    ReviewDecision,
    RunInputs,
    ScreenshotRef,
    TicketDraft,
    TicketType,
    Transcript,
)
from app.prompts import system_prompt
from app.providers.base import CodeProvider, FileEntry, JiraProvider
from app.providers.transcript import ManualUploadProvider, render_transcript
from app.services.search import render_hits
from app.services.tickets import create_approved_tickets

TREE_LISTING_LIMIT = 1500
MAX_REQUIREMENTS = 40
_WORD = re.compile(r"[a-z0-9]+")
_SOURCE_EXTENSIONS = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".kt", ".go", ".rb", ".cs", ".php", ".vue"}
    | {".svelte", ".swift", ".rs", ".html", ".css", ".scss"}
)


class ApprovalRequired(RuntimeError):
    """create_tickets ran without an approved review. Nothing was written to Jira."""


@dataclass
class Deps:
    settings: Settings
    db: Database
    llm: LLM
    code: Callable[[], CodeProvider]
    jira: Callable[[], JiraProvider]


class Nodes:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    # ---------- inputs ----------

    async def load_transcript(self, state: RunState) -> dict[str, Any]:
        transcript = ManualUploadProvider().load(state["transcript_path"])
        speakers = {s.speaker for s in transcript.segments if s.speaker}
        return {
            "transcript": transcript.model_dump(),
            "_summary": f"{len(transcript.segments)} segments, {len(speakers)} speakers",
        }

    # ---------- LLM steps ----------

    async def analyze_meeting(self, state: RunState) -> dict[str, Any]:
        content: list[Part] = [Text(_transcript_block(state))]
        for shot in _screenshots(state):
            data = await asyncio.to_thread(Path(shot.path).read_bytes)
            caption = f' caption="{_attr(shot.caption)}"' if shot.caption else ""
            content.append(Text(f'<screenshot number="{shot.order}"{caption}/>'))
            content.append(Image(media_type=_media_type(shot.path), data=data))
        content.append(Text("Summarise this meeting per screen."))
        result = await self.deps.llm.structured(
            step="analyze_meeting",
            system=system_prompt("analyze_meeting"),
            content=content,
            output=MeetingAnalysis,
            tokens_used=state.get("tokens_used", 0),
        )
        analysis = result.output
        return {
            "meeting_analysis": analysis.model_dump(),
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "_summary": f"{len(analysis.screens)} screens",
        }

    async def extract_requirements(self, state: RunState) -> dict[str, Any]:
        content: list[Part] = [
            Text(_transcript_block(state)),
            Text(_json_block("meeting_summary", state.get("meeting_analysis"))),
            Text("List the requirements."),
        ]
        result = await self.deps.llm.structured(
            step="extract_requirements",
            system=system_prompt("extract_requirements"),
            content=content,
            output=RequirementList,
            tokens_used=state.get("tokens_used", 0),
        )
        requirements = _renumber_requirements(result.output.requirements[:MAX_REQUIREMENTS])
        return {
            "requirements": [r.model_dump() for r in requirements],
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "_summary": f"{len(requirements)} requirements",
        }

    async def plan_code_reading(self, state: RunState) -> dict[str, Any]:
        inputs = RunInputs.model_validate(state["inputs"])
        requirements = _requirements(state)
        tree = await self.deps.code().list_tree(inputs.repo, inputs.branch)
        known = {e.path for e in tree}
        listing = rank_paths(tree, requirements)[:TREE_LISTING_LIMIT]
        max_files = self.deps.settings.max_code_files
        content: list[Part] = [
            Text(_json_block("requirements", [r.model_dump() for r in requirements])),
            Text(
                "<file_listing>\n"
                + "\n".join(f"{e.path} ({e.size or 0} bytes)" for e in listing)
                + "\n</file_listing>"
            ),
            Text(f"Choose up to {max_files} files to read."),
        ]
        result = await self.deps.llm.structured(
            step="plan_code_reading",
            system=system_prompt("plan_code_reading", max_files=max_files),
            content=content,
            output=CodePlan,
            tokens_used=state.get("tokens_used", 0),
        )
        chosen = list(dict.fromkeys(p.strip().lstrip("/") for p in result.output.paths))
        valid = [p for p in chosen if p in known]
        invented = len(chosen) - len(valid)
        if not valid:
            valid = [e.path for e in listing]
        candidates = valid[:max_files]
        summary = f"{len(candidates)} of {len(tree)} files chosen"
        if invented:
            summary += f"; ignored {invented} path(s) not in the repository"
        return {
            "code_candidates": candidates,
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "_summary": summary,
        }

    async def read_code(self, state: RunState) -> dict[str, Any]:
        """No LLM. Fetch candidates within the per-file and total byte budgets."""
        inputs = RunInputs.model_validate(state["inputs"])
        settings = self.deps.settings
        code = self.deps.code()
        files: dict[str, str] = {}
        total = 0
        skipped = 0
        for path in state.get("code_candidates", []):
            text = await code.get_file(inputs.repo, inputs.branch, path, settings.max_file_bytes)
            if text is None:
                skipped += 1
                continue
            size = len(text.encode("utf-8"))
            if total + size > settings.max_total_code_bytes:
                skipped += 1
                continue
            files[path] = text
            total += size
        summary = f"read {len(files)} files ({total:,} bytes)"
        if skipped:
            summary += f", skipped {skipped} (binary, too large or over budget)"
        return {"code_files": files, "_summary": summary}

    async def compare_with_code(self, state: RunState) -> dict[str, Any]:
        requirements = _requirements(state)
        files = state.get("code_files", {})
        content: list[Part] = [
            Text(_json_block("requirements", [r.model_dump() for r in requirements])),
            *[Text(_file_block(path, text)) for path, text in files.items()],
            Text(render_hits(requirements, files)),
            Text("Return one finding per requirement."),
        ]
        result = await self.deps.llm.structured(
            step="compare_with_code",
            system=system_prompt("compare_with_code"),
            content=content,
            output=FindingList,
            tokens_used=state.get("tokens_used", 0),
        )
        findings = check_findings(result.output.findings, requirements, files)
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.status] = counts.get(f.status, 0) + 1
        return {
            "code_findings": [f.model_dump() for f in findings],
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "_summary": ", ".join(f"{n} {status}" for status, n in sorted(counts.items())),
        }

    async def draft_tickets(self, state: RunState) -> dict[str, Any]:
        inputs = RunInputs.model_validate(state["inputs"])
        requirements = _requirements(state)
        findings = [CodeFinding.model_validate(f) for f in state.get("code_findings", [])]
        content: list[Part] = [
            Text(_json_block("meeting_summary", state.get("meeting_analysis"))),
            Text(_json_block("requirements", [r.model_dump() for r in requirements])),
            Text(_json_block("code_findings", [f.model_dump() for f in findings])),
            Text("Allowed issue types: " + ", ".join(inputs.issue_types)),
            Text("Draft the tickets."),
        ]
        result = await self.deps.llm.structured(
            step="draft_tickets",
            system=system_prompt("draft_tickets"),
            content=content,
            output=DraftList,
            tokens_used=state.get("tokens_used", 0),
        )
        drafts = finalize_drafts(
            result.output, requirements, findings, inputs.issue_types, state.get("code_files", {})
        )
        self.deps.db.replace_drafts(state["run_id"], drafts)
        return {
            "drafts": [d.model_dump() for d in drafts],
            "tokens_used": state.get("tokens_used", 0) + result.tokens,
            "_summary": f"{len(drafts)} draft tickets",
        }

    # ---------- review and write ----------

    async def human_review(self, state: RunState) -> dict[str, Any]:
        # Nothing with side effects before interrupt(): this node re-runs from the top on
        # resume. Never wrap interrupt() in try/except.
        decision = interrupt({"run_id": state["run_id"], "drafts": len(state.get("drafts", []))})
        review = ReviewDecision.model_validate(decision)
        return {"review": review.model_dump()}

    async def create_tickets(self, state: RunState) -> dict[str, Any]:
        review_data = state.get("review")
        if not review_data:
            raise ApprovalRequired("create_tickets refused: the run has no review decision")
        review = ReviewDecision.model_validate(review_data)
        if review.decision != "approve":
            raise ApprovalRequired("create_tickets refused: the review was not an approval")
        selected = [d for d in review.drafts if d.selected]
        inputs = RunInputs.model_validate(state["inputs"])
        created = await create_approved_tickets(
            self.deps.jira(), inputs.jira_project_key, state["run_id"], selected
        )
        for c in created:
            if c.key and c.url:
                self.deps.db.set_draft_jira(state["run_id"], c.temp_id, c.key, c.url)
        failed = sum(1 for c in created if c.error)
        existed = sum(1 for c in created if c.existed)
        made = len(created) - failed - existed
        summary = f"{made} created"
        if existed:
            summary += f", {existed} already existed"
        if failed:
            summary += f", {failed} failed"
        return {"created": [c.model_dump() for c in created], "_summary": summary}

    async def finalize(self, state: RunState) -> dict[str, Any]:
        return {}


def route_after_review(state: RunState) -> str:
    review = state.get("review") or {}
    return "create_tickets" if review.get("decision") == "approve" else "finalize"


# ---------- checks on LLM output (pure, unit-tested) ----------


def rank_paths(tree: list[FileEntry], requirements: list[Requirement]) -> list[FileEntry]:
    """Order paths by word overlap with the requirements; source files first on ties."""
    words: set[str] = set()
    for r in requirements:
        words |= set(_WORD.findall(f"{r.title} {r.detail} {r.screen or ''}".lower()))
    words = {w for w in words if len(w) > 2}

    def score(entry: FileEntry) -> tuple[int, int, str]:
        tokens = set(_WORD.findall(re.sub(r"([a-z])([A-Z])", r"\1 \2", entry.path).lower()))
        hits = len(tokens & words)
        source = 1 if Path(entry.path).suffix.lower() in _SOURCE_EXTENSIONS else 0
        return (-hits, -source, entry.path)

    return sorted(tree, key=score)


def check_findings(
    findings: list[CodeFinding], requirements: list[Requirement], files: dict[str, str]
) -> list[CodeFinding]:
    """One finding per requirement, with evidence only from files that were actually read."""
    line_counts = {path: text.count("\n") + 1 for path, text in files.items()}
    by_req: dict[str, CodeFinding] = {}
    for f in findings:
        if f.requirement_id in by_req:
            continue
        evidence = [e for e in f.evidence if _evidence_ok(e, line_counts)]
        status, confidence = f.status, f.confidence
        if status in ("implemented", "partial") and not evidence:
            status, confidence = "unclear", "low"
        elif len(evidence) < len(f.evidence) and confidence == "high":
            confidence = "medium"
        by_req[f.requirement_id] = f.model_copy(
            update={
                "status": status,
                "confidence": confidence,
                "evidence": evidence,
                "affected_files": [p for p in dict.fromkeys(f.affected_files) if p in files]
                or [e.path for e in evidence],
            }
        )
    out = []
    for r in requirements:
        out.append(
            by_req.get(r.id)
            or CodeFinding(
                requirement_id=r.id,
                status="unclear",
                evidence=[],
                affected_files=[],
                confidence="low",
            )
        )
    return out


def finalize_drafts(
    drafted: DraftList,
    requirements: list[Requirement],
    findings: list[CodeFinding],
    allowed_types: list[TicketType],
    files: dict[str, str],
) -> list[TicketDraft]:
    known_reqs = {r.id for r in requirements}
    finding_by_req = {f.requirement_id: f for f in findings}
    seen_titles: dict[str, TicketDraft] = {}
    drafts: list[TicketDraft] = []
    for out in drafted.drafts:
        title = " ".join(out.title.split())[:200]
        if not title:
            continue
        req_ids = [r for r in dict.fromkeys(out.requirement_ids) if r in known_reqs]
        key = title.lower()
        if key in seen_titles:  # duplicate: merge requirement ids into the first one
            first = seen_titles[key]
            merged = list(dict.fromkeys([*first.requirement_ids, *req_ids]))
            idx = drafts.index(first)
            drafts[idx] = first.model_copy(update={"requirement_ids": merged})
            seen_titles[key] = drafts[idx]
            continue
        linked = [finding_by_req[r] for r in req_ids if r in finding_by_req]
        already_done_sure = (
            out.status_in_code == "already_done"
            and bool(linked)
            and all(f.status == "implemented" and f.confidence == "high" for f in linked)
        )
        ticket_type = out.type if out.type in allowed_types else allowed_types[0]
        draft = TicketDraft(
            temp_id=f"T{len(drafts) + 1}",
            type=ticket_type,
            title=title,
            description=out.description.strip(),
            acceptance_criteria=[c.strip() for c in out.acceptance_criteria if c.strip()],
            estimate=out.estimate,
            labels=list(dict.fromkeys(lbl.strip().lower() for lbl in out.labels if lbl.strip()))[
                :5
            ],
            related_files=[p for p in dict.fromkeys(out.related_files) if p in files],
            requirement_ids=req_ids,
            status_in_code=out.status_in_code,
            selected=not already_done_sure,
        )
        drafts.append(draft)
        seen_titles[key] = draft
    return drafts


# ---------- helpers ----------


def _requirements(state: RunState) -> list[Requirement]:
    return [Requirement.model_validate(r) for r in state.get("requirements", [])]


def _screenshots(state: RunState) -> list[ScreenshotRef]:
    shots = [ScreenshotRef.model_validate(s) for s in state.get("screenshots", [])]
    return sorted(shots, key=lambda s: s.order)


def _renumber_requirements(requirements: list[Requirement]) -> list[Requirement]:
    return [r.model_copy(update={"id": f"R{i}"}) for i, r in enumerate(requirements, start=1)]


def _transcript_block(state: RunState) -> str:
    transcript = Transcript.model_validate(state.get("transcript"))
    title = f' title="{_attr(transcript.title)}"' if transcript.title else ""
    return f"<transcript{title}>\n{render_transcript(transcript)}\n</transcript>"


def _json_block(tag: str, value: Any) -> str:
    return f"<{tag}>\n{json.dumps(value, ensure_ascii=False, indent=1)}\n</{tag}>"


def _file_block(path: str, text: str) -> str:
    numbered = "\n".join(f"{i:>4}| {line}" for i, line in enumerate(text.split("\n"), start=1))
    return f'<file path="{_attr(path)}">\n{numbered}\n</file>'


def _attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")


def _evidence_ok(e: Evidence, line_counts: dict[str, int]) -> bool:
    lines = line_counts.get(e.path)
    if lines is None:
        return False
    start, end = e.start_line, e.end_line
    if start is not None and not 1 <= start <= lines:
        return False
    if end is not None and not 1 <= end <= lines:
        return False
    return start is None or end is None or start <= end
