"""New runs: validate every upload in memory, then store files under data/runs/<run_id>/."""

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.db import Database, Run
from app.graph.state import RunState
from app.models import RunInputs, ScreenshotRef, Transcript
from app.providers.base import CodeProvider, JiraProvider
from app.providers.transcript import SUPPORTED_EXTENSIONS, TranscriptError, parse_transcript
from app.services.tickets import UnfillableFields, check_required_fields
from app.uploads import CleanImage, UploadError, clean_screenshot

# Rough per-run token estimate (shown before starting; enforced separately by the budget).
_PROMPT_OVERHEAD = 1_500
_TOKENS_PER_IMAGE = 1_600
_TRANSCRIPT_READS = 3  # analyze, extract (transcript), and the summary passed on
_OUTPUT_PER_STEP = 2_500
_LLM_STEPS = 5


class IntakeError(ValueError):
    """The request is invalid. The message is safe to show."""


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    data: bytes


@dataclass(frozen=True)
class NewRunRequest:
    inputs_json: str
    transcript_text: str | None
    transcript_file: UploadedFile | None
    screenshots: list[UploadedFile]
    captions_json: str


@dataclass(frozen=True)
class _Prepared:
    inputs: RunInputs
    transcript_name: str
    transcript_bytes: bytes
    transcript: Transcript
    images: list[CleanImage]
    captions: list[str | None]


async def create_run(
    request: NewRunRequest,
    settings: Settings,
    db: Database,
    code: CodeProvider,
    jira: JiraProvider,
) -> tuple[Run, RunState]:
    prepared = _prepare(request, settings)
    await _check_targets(prepared.inputs, code, jira)

    run = db.create_run(prepared.inputs)
    folder = settings.runs_dir / run.id
    shots_dir = folder / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = folder / prepared.transcript_name
    transcript_path.write_bytes(prepared.transcript_bytes)

    refs: list[ScreenshotRef] = []
    for order, (image, caption) in enumerate(
        zip(prepared.images, prepared.captions, strict=True), start=1
    ):
        path = shots_dir / f"{order:02d}{image.extension}"
        path.write_bytes(image.data)
        refs.append(ScreenshotRef(path=str(path), order=order, caption=caption))

    state: RunState = {
        "run_id": run.id,
        "inputs": prepared.inputs.model_dump(),
        "transcript_path": str(transcript_path),
        "screenshots": [r.model_dump() for r in refs],
        "tokens_used": 0,
        "errors": [],
    }
    return run, state


def estimate_tokens(transcript_chars: int, screenshots: int, settings: Settings) -> int:
    transcript = transcript_chars // 4
    code = min(settings.max_total_code_bytes, settings.max_code_files * 6_000) // 4
    return (
        _LLM_STEPS * (_PROMPT_OVERHEAD + _OUTPUT_PER_STEP)
        + _TRANSCRIPT_READS * transcript
        + screenshots * _TOKENS_PER_IMAGE
        + code
        + 3_000  # file listing
    )


def _prepare(request: NewRunRequest, settings: Settings) -> _Prepared:
    try:
        inputs = RunInputs.model_validate_json(request.inputs_json)
    except ValidationError as e:
        fields = ", ".join(".".join(str(p) for p in err["loc"]) or "inputs" for err in e.errors())
        raise IntakeError(f"Invalid run settings: {fields}") from None

    text = (request.transcript_text or "").strip()
    if bool(text) == (request.transcript_file is not None):
        raise IntakeError("Provide either a transcript file or pasted text, not both or neither")
    if request.transcript_file is not None:
        name = request.transcript_file.filename or "transcript.txt"
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise IntakeError(f"Transcript must be one of {', '.join(SUPPORTED_EXTENSIONS)}")
        data = request.transcript_file.data
        stored_name = f"transcript{ext}"
        title_source = name
    else:
        data = text.encode("utf-8")
        stored_name = "transcript.txt"
        title_source = "Pasted transcript.txt"
    if len(data) > settings.max_transcript_bytes:
        raise IntakeError(
            f"Transcript is larger than {settings.max_transcript_bytes // 1_000_000} MB"
        )
    try:
        transcript = parse_transcript(title_source, data)
    except TranscriptError as e:
        raise IntakeError(str(e)) from None

    if len(request.screenshots) > settings.max_screenshots:
        raise IntakeError(f"At most {settings.max_screenshots} screenshots per run")
    captions = _captions(request.captions_json, len(request.screenshots))
    images: list[CleanImage] = []
    for i, shot in enumerate(request.screenshots, start=1):
        label = shot.filename or f"screenshot {i}"
        try:
            images.append(clean_screenshot(shot.data, label, settings.max_screenshot_bytes))
        except UploadError as e:
            raise IntakeError(str(e)) from None

    return _Prepared(
        inputs=inputs,
        transcript_name=stored_name,
        transcript_bytes=data,
        transcript=transcript,
        images=images,
        captions=captions,
    )


def _captions(raw: str, count: int) -> list[str | None]:
    try:
        values = json.loads(raw or "[]")
    except json.JSONDecodeError:
        raise IntakeError("captions must be a JSON list of strings") from None
    if not isinstance(values, list) or len(values) > count:
        raise IntakeError("captions must be a JSON list with one entry per screenshot")
    out: list[str | None] = []
    for v in [*values, *([None] * (count - len(values)))]:
        if v is not None and not isinstance(v, str):
            raise IntakeError("each caption must be a string or null")
        caption = (v or "").strip()[:300]
        out.append(caption or None)
    return out


async def _check_targets(inputs: RunInputs, code: CodeProvider, jira: JiraProvider) -> None:
    branches = await code.list_branches(inputs.repo)
    if inputs.branch not in branches:
        raise IntakeError(f"Branch {inputs.branch!r} not found in {inputs.repo}")
    projects = {p.key for p in await jira.list_projects()}
    if inputs.jira_project_key not in projects:
        raise IntakeError(f"Jira project {inputs.jira_project_key!r} not found")
    types = {t.name for t in await jira.list_issue_types(inputs.jira_project_key)}
    unknown = [t for t in inputs.issue_types if t not in types]
    if unknown:
        raise IntakeError(f"Issue type(s) not in {inputs.jira_project_key}: {', '.join(unknown)}")
    # Fail now rather than after the whole pipeline if Jira needs fields we cannot fill.
    try:
        await check_required_fields(jira, inputs.jira_project_key, list(inputs.issue_types))
    except UnfillableFields as e:
        raise IntakeError(str(e)) from None


async def create_rerun(
    source: Run,
    values: dict[str, Any],
    repo: str,
    branch: str,
    settings: Settings,
    db: Database,
    code: CodeProvider,
) -> tuple[Run, RunState]:
    """A new run on another repository that reuses the source run's meeting work.

    The transcript and screenshots are copied, and the meeting analysis and requirements are
    carried over, so only the code steps and the drafting call Claude again.
    """
    if not values.get("requirements"):
        raise IntakeError("This run has no requirements to reuse yet")
    branches = await code.list_branches(repo)
    if branch not in branches:
        raise IntakeError(f"Branch {branch!r} not found in {repo}")
    inputs = source.inputs.model_copy(update={"repo": repo, "branch": branch})

    run = db.create_run(inputs)
    try:
        transcript_path, refs = await asyncio.to_thread(
            _copy_inputs, values, settings.runs_dir, settings.runs_dir / run.id
        )
    except (IntakeError, OSError) as e:
        message = str(e) if isinstance(e, IntakeError) else "Could not copy the source files"
        db.set_status(run.id, "failed", message)
        raise IntakeError(message) from e
    state: RunState = {
        "run_id": run.id,
        "inputs": inputs.model_dump(),
        "transcript_path": str(transcript_path),
        "screenshots": refs,
        "meeting_analysis": values.get("meeting_analysis"),
        "requirements": values["requirements"],
        "tokens_used": 0,
        "errors": [],
    }
    return run, state


def _copy_inputs(
    values: dict[str, Any], runs_dir: Path, folder: Path
) -> tuple[Path, list[dict[str, Any]]]:
    """Copy the source run's transcript and screenshots into a new run folder."""
    runs_root = runs_dir.resolve()
    shots_dir = folder / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    old_transcript = Path(values["transcript_path"]).resolve()
    if not old_transcript.is_relative_to(runs_root) or not old_transcript.is_file():
        raise IntakeError("The source run's transcript is missing")
    transcript_path = folder / old_transcript.name
    shutil.copyfile(old_transcript, transcript_path)

    refs: list[dict[str, Any]] = []
    for item in values.get("screenshots", []):
        ref = ScreenshotRef.model_validate(item)
        old = Path(ref.path).resolve()
        if not old.is_relative_to(runs_root) or not old.is_file():
            continue
        new = shots_dir / old.name
        shutil.copyfile(old, new)
        refs.append(ref.model_copy(update={"path": str(new)}).model_dump())
    return transcript_path, refs
