import io

import pytest
from docx import Document

from app.providers.transcript import (
    ManualUploadProvider,
    TranscriptError,
    parse_text,
    parse_transcript,
    parse_vtt,
    render_transcript,
)
from tests.conftest import FIXTURES


def test_fixture_vtt_has_speakers_and_times() -> None:
    t = ManualUploadProvider().load(str(FIXTURES / "transcript.vtt"))
    assert len(t.segments) == 16
    assert {s.speaker for s in t.segments} == {"Anna Rossi", "Marco Bianchi", "Luca Verdi"}
    assert t.segments[0].start_s == 2.0
    assert t.segments[1].text.startswith("Main thing on login")
    assert t.title and "Design review" in t.title


def test_vtt_without_voice_tags_strips_markup_and_skips_metadata() -> None:
    vtt = (
        "WEBVTT\n\nSTYLE\n::cue { color: red }\n\n"
        "1\n00:01.000 --> 00:02.000\n<b>Hello</b> &amp; welcome\n\n"
        "00:00:03.500 --> 00:00:04.000 align:start\nsecond line\ncontinues\n"
    )
    t = parse_vtt(vtt)
    assert [(s.speaker, s.start_s, s.text) for s in t.segments] == [
        (None, 1.0, "Hello & welcome"),
        (None, 3.5, "second line continues"),
    ]


def test_vtt_requires_header_and_cues() -> None:
    with pytest.raises(TranscriptError):
        parse_vtt("00:01.000 --> 00:02.000\nhi")
    with pytest.raises(TranscriptError):
        parse_vtt("WEBVTT\n\nNOTE nothing here\n")


def test_text_with_consistent_speakers() -> None:
    t = parse_text(
        "Anna: Let's start.\nMarco: We need a CSV export.\nit should match the table\n"
        "Anna: Agreed.\nMarco: Ship it."
    )
    assert [s.speaker for s in t.segments] == ["Anna", "Marco", "Anna", "Marco"]
    assert t.segments[1].text == "We need a CSV export. it should match the table"


def test_text_without_speakers_splits_paragraphs() -> None:
    t = parse_text("Notes from the call.\nWe talked about login.\n\nNext: dashboard filters.")
    assert [s.speaker for s in t.segments] == [None, None]
    assert t.segments[0].text == "Notes from the call. We talked about login."


def test_occasional_colons_are_not_speakers() -> None:
    t = parse_text("Agenda: login and dashboard.\nWe started late.\nThen we reviewed screens.")
    assert all(s.speaker is None for s in t.segments)


def test_docx() -> None:
    doc = Document()
    doc.add_paragraph("Anna: Hello")
    doc.add_paragraph("Marco: Add an empty state.")
    doc.add_paragraph("Anna: Thanks.")
    buf = io.BytesIO()
    doc.save(buf)
    t = parse_transcript("Review.docx", buf.getvalue())
    assert t.title == "Review"
    assert [s.speaker for s in t.segments] == ["Anna", "Marco", "Anna"]


def test_bad_docx_and_unknown_type_are_rejected() -> None:
    with pytest.raises(TranscriptError, match=r"\.docx"):
        parse_transcript("x.docx", b"not a zip")
    with pytest.raises(TranscriptError, match="Unsupported"):
        parse_transcript("x.pdf", b"%PDF")
    with pytest.raises(TranscriptError, match="empty"):
        parse_transcript("x.txt", b"  \n \n")


def test_render_includes_stamp_from_zero_seconds() -> None:
    t = parse_vtt("WEBVTT\n\n00:00.000 --> 00:01.000\n<v Anna>Hi\n")
    assert render_transcript(t) == "[00:00] Anna: Hi"
