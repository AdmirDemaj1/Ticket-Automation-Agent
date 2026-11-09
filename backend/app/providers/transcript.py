"""Turn an uploaded or pasted transcript into a `Transcript`.

Supported: WebVTT (`.vtt`), plain text (`.txt` or pasted) and Word (`.docx`).
`ManualUploadProvider` is the only `TranscriptProvider` in v1; Teams or Spinach providers
can implement the same Protocol later.
"""

import html
import io
import re
from pathlib import Path

from app.models import Segment, Transcript

SUPPORTED_EXTENSIONS = (".vtt", ".txt", ".docx")

_TIMING = re.compile(
    r"^(?P<start>(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s+-->\s+"
    r"(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
)
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")
_TAG = re.compile(r"</?[^>]+>")
_SPEAKER_LINE = re.compile(r"^(?P<name>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3})\s*:\s+(?P<text>\S.*)$")


class TranscriptError(ValueError):
    """The transcript is empty or cannot be read. The message is safe to show."""


def parse_transcript(filename: str, data: bytes) -> Transcript:
    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        transcript = parse_docx(data)
    elif ext in (".vtt", ".txt"):
        text = _decode(data)
        transcript = parse_vtt(text) if ext == ".vtt" else parse_text(text)
    else:
        raise TranscriptError(
            f"Unsupported transcript type {ext or '(none)'}; use {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return transcript.model_copy(update={"title": transcript.title or Path(filename).stem})


def parse_vtt(text: str) -> Transcript:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or not lines[0].lstrip("﻿").startswith("WEBVTT"):
        raise TranscriptError("Not a WebVTT file: the first line must start with WEBVTT")
    title: str | None = None
    segments: list[Segment] = []
    blocks = _blocks(lines[1:])
    for block in blocks:
        first = block[0]
        if first.startswith("NOTE"):
            note = " ".join([first.removeprefix("NOTE").strip(), *block[1:]]).strip()
            title = title or note or None
            continue
        if first.startswith(("STYLE", "REGION")):
            continue
        found = [(i, m) for i, line in enumerate(block[:2]) if (m := _TIMING.match(line))]
        if not found:
            continue
        timing_index, match = found[0]
        payload = " ".join(block[timing_index + 1 :]).strip()
        voice = _VOICE.search(payload)
        speaker = voice.group(1).strip() if voice else None
        cue_text = html.unescape(_TAG.sub("", payload)).strip()
        if cue_text:
            segments.append(
                Segment(speaker=speaker, start_s=_seconds(match["start"]), text=cue_text)
            )
    if not segments:
        raise TranscriptError("The WebVTT file has no cues with text")
    return Transcript(title=title, segments=segments)


def parse_text(text: str) -> Transcript:
    """Paragraphs, or speaker turns when most lines look like `Name: text`."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    content = [line for line in lines if line]
    if not content:
        raise TranscriptError("The transcript is empty")

    matches = [_SPEAKER_LINE.match(line) for line in content]
    names = {m["name"] for m in matches if m}
    hits = sum(1 for m in matches if m)
    # "Consistent" speakers: most lines are turns, and at least one name repeats.
    if hits >= 2 and hits / len(content) >= 0.6 and len(names) < hits:
        segments: list[Segment] = []
        for line, m in zip(content, matches, strict=True):
            if m:
                segments.append(Segment(speaker=m["name"], text=m["text"].strip()))
            elif segments:
                last = segments[-1]
                segments[-1] = last.model_copy(update={"text": f"{last.text} {line}"})
            else:
                segments.append(Segment(text=line))
        return Transcript(segments=segments)

    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    return Transcript(segments=[Segment(text=p) for p in paragraphs])


def parse_docx(data: bytes) -> Transcript:
    from docx import Document  # local import: python-docx is slow to import

    try:
        document = Document(io.BytesIO(data))
    except Exception as e:  # python-docx raises several unrelated types for bad files
        raise TranscriptError("Could not read the .docx file") from e
    text = "\n".join(p.text for p in document.paragraphs)
    return parse_text(text)


def render_transcript(transcript: Transcript) -> str:
    """One line per segment, for prompts: `[mm:ss] Speaker: text`."""
    out = []
    for seg in transcript.segments:
        stamp = ""
        if seg.start_s is not None:
            stamp = f"[{int(seg.start_s // 60):02d}:{int(seg.start_s % 60):02d}] "
        who = f"{seg.speaker}: " if seg.speaker else ""
        out.append(f"{stamp}{who}{seg.text}")
    return "\n".join(out)


class ManualUploadProvider:
    """Reads a transcript file the user uploaded (or pasted text saved as .txt)."""

    def load(self, source: str) -> Transcript:
        path = Path(source)
        return parse_transcript(path.name, path.read_bytes())


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")
