from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from hackathon26.listener.detect import detect_mentions
from hackathon26.listener.models import TranscriptSegment


def segment(input_text, **updates):
    return TranscriptSegment(
        **({"schema_version": "1", "event_id": "evt-1", "consultation_id": "demo-1",
            "segment_id": "seg-1", "revision": 1, "sequence": 1, "speaker": "PATIENT",
            "text": input_text, "is_final": True, "source": "script",
            "occurred_at": datetime(2026, 11, 13, tzinfo=timezone.utc)} | updates)
    )


def test_named_medicine_preserves_original_unicode_span():
    text = "💬 I take RAMIPRIL."
    result = detect_mentions(segment(text))
    mention = result.mentions[0]
    assert (mention.raw_text, mention.kind) == ("RAMIPRIL", "NAME")
    assert (mention.start, mention.end) == (9, 17)
    assert text[mention.start:mention.end] == mention.raw_text
    assert mention.subject == "PATIENT"
    assert mention.assertion == "AFFIRMED"
    assert mention.needs_review is True
    assert result.limitations


def test_appearance_does_not_resolve_a_drug():
    result = detect_mentions(segment("I take the little white one."))
    mention = result.mentions[0]
    assert mention.kind == "APPEARANCE"
    assert mention.raw_text == "the little white one"
    assert mention.clarification
    assert "drug_id" not in mention.model_dump()


def test_knee_painkiller_remains_unidentified():
    result = detect_mentions(segment("I take something for my knee."))
    assert len(result.mentions) == 1
    assert result.mentions[0].kind == "INDICATION"
    assert result.mentions[0].raw_text == "something for my knee"
    assert "ibuprofen" not in result.model_dump_json().lower()
    assert "nsaid" not in result.model_dump_json().lower()


@pytest.mark.parametrize("text,assertion,subject,temporal", [
    ("I don't take ibuprofen.", "NEGATED", "PATIENT", "UNKNOWN"),
    ("I no longer take ibuprofen.", "NEGATED", "PATIENT", "HISTORICAL"),
    ("I used to take ibuprofen.", "UNCERTAIN", "PATIENT", "HISTORICAL"),
    ("My husband takes ibuprofen.", "AFFIRMED", "OTHER", "CURRENT"),
    ("Maybe I take ibuprofen.", "UNCERTAIN", "PATIENT", "UNKNOWN"),
    ("Do you take ibuprofen?", "UNCERTAIN", "UNKNOWN", "UNKNOWN"),
    ("Ibuprofen.", "UNCERTAIN", "UNKNOWN", "UNKNOWN"),
])
def test_context_does_not_assert_current_patient_exposure(text, assertion, subject, temporal):
    mention = detect_mentions(segment(text)).mentions[0]
    assert (mention.assertion, mention.subject, mention.temporal) == (assertion, subject, temporal)


def test_sentence_context_does_not_leak_from_another_person():
    mentions = detect_mentions(segment("My husband takes ibuprofen. I take ramipril.")).mentions
    assert [m.subject for m in mentions] == ["OTHER", "PATIENT"]


def test_mixed_subject_clause_is_uncertain():
    mention = detect_mentions(segment("My husband says I take ibuprofen.")).mentions[0]
    assert mention.subject == "UNKNOWN"


@pytest.mark.parametrize("text,expected", [
    ("I take ramipril but not ibuprofen.", [("AFFIRMED", "PATIENT", "CURRENT"), ("NEGATED", "UNKNOWN", "UNKNOWN")]),
    ("I don't take ibuprofen but I take ramipril.", [("NEGATED", "PATIENT", "UNKNOWN"), ("AFFIRMED", "PATIENT", "CURRENT")]),
    ("I take ramipril and she takes ibuprofen.", [("AFFIRMED", "PATIENT", "CURRENT"), ("AFFIRMED", "OTHER", "CURRENT")]),
    ("I take ibuprofen, but that was years ago.", [("UNCERTAIN", "PATIENT", "HISTORICAL")]),
    ("I will take ibuprofen tomorrow.", [("UNCERTAIN", "UNKNOWN", "UNKNOWN")]),
])
def test_compound_context_does_not_invent_current_patient_exposure(text, expected):
    mentions = detect_mentions(segment(text)).mentions
    assert [(m.assertion, m.subject, m.temporal) for m in mentions] == expected


def test_partial_segment_has_no_durable_mentions():
    result = detect_mentions(segment("I take ibuprofen", is_final=False))
    assert result.status == "PROVISIONAL"
    assert result.mentions == []


def test_no_match_reports_limited_coverage():
    result = detect_mentions(segment("Nice weather today."))
    assert result.status == "ANALYZED"
    assert result.mentions == []
    assert any("not" in note.lower() for note in result.limitations)


@pytest.mark.parametrize("updates", [
    {"sequence": 0}, {"revision": 0}, {"speaker": "NURSE"}, {"source": "microphone"},
    {"text": "   "}, {"text": "x" * 4001}, {"extra": "ignored?"},
    {"is_final": "false"}, {"occurred_at": "2026-11-13T10:00:00"},
])
def test_invalid_segment_is_rejected(updates):
    with pytest.raises(ValidationError):
        segment("I take ramipril.", **updates)
