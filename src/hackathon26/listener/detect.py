"""Conservative English demo rules, not a general clinical language parser."""

import re

from .models import ListenerResult, Mention, TranscriptSegment

_NAMES = re.compile(
    r"\b(?:ramipril|metoprolol|furosemide|ibuprofen|spironolactone|paracetamol)\b", re.I
)
_APPEARANCE = re.compile(
    r"\b(?:(?:the|a)\s+)?(?:(?:small|little|large)\s+)?"
    r"(?:(?:round|oval|oblong|long)\s+)?(?:white|yellow|red|blue|pink)"
    r"(?:\s+(?:round|oval|oblong|long))?\s+(?:one|ones|pill|pills|tablet|tablets|capsule|capsules)\b", re.I
)
_INDICATION = re.compile(
    r"\b(?:something\s+for\s+(?:my\s+)?(?:knee|pain)|painkillers?|water\s+tablet)\b", re.I
)
_CLAUSE_BREAK = re.compile(r"\bbut\b|\band\b(?=\s+(?:i|he|she|they|my)\b)", re.I)
_PAST = re.compile(r"\b(?:used to|no longer|stopped|previously|years? ago|months? ago|yesterday)\b", re.I)
_LIMITATIONS = [
    "Limited English demo vocabulary and heuristic context rules; not all medication mentions are detected.",
    "Transcript matches are not confirmed medication identities or evidence of current exposure.",
    "No patient medication list, lab results or drug-label evidence checked; no interaction assessment performed.",
    "Clinician must verify the product and context before using any mention downstream.",
]


def _context(text: str, start: int, end: int) -> str:
    left = max((m.end() for m in re.finditer(r"[.!?;\n]", text[:start])), default=0)
    boundary = re.search(r"[.!?;\n]", text[end:])
    right = end + boundary.end() if boundary else len(text)
    sentence = text[left:right].lower().replace("’", "'")
    relative_start = start - left
    clause_left, clause_right = 0, len(sentence)
    for boundary in _CLAUSE_BREAK.finditer(sentence):
        if boundary.end() <= relative_start:
            clause_left = boundary.end()
        elif boundary.start() >= end - left:
            clause_right = boundary.start()
            break
    context = sentence[clause_left:clause_right]
    # A trailing time correction can qualify a preceding clause. Conservatively
    # avoid current-exposure claims throughout a sentence containing such a cue.
    if _PAST.search(sentence):
        context += " previously"
    if "?" in sentence:
        context += "?"
    return context


def _attributes(context: str, speaker: str) -> tuple[str, str, str]:
    personal = bool(re.search(r"\bi\s+(?:(?:don't|do not|no longer|used to|might|may)\s+)?take\b", context))
    other = bool(re.search(r"\b(?:my\s+(?:husband|wife|mother|father|daughter|son)|he|she|they)\b", context))
    subject = "UNKNOWN" if personal and other else "OTHER" if other else "PATIENT" if personal else "UNKNOWN"
    historical = bool(_PAST.search(context))
    negated = bool(re.search(r"\b(?:don't|do not|not|no longer|never|stopped)\b", context)) and "not sure" not in context
    uncertain = historical or "?" in context or bool(re.search(r"\b(?:maybe|might|may|not sure|will|tomorrow|next week)\b", context))
    affirmed = bool(re.search(r"\b(?:take|takes|taking)\b", context))
    assertion = "NEGATED" if negated else "AFFIRMED" if affirmed and not uncertain else "UNCERTAIN"
    temporal = "HISTORICAL" if historical else "CURRENT" if assertion == "AFFIRMED" else "UNKNOWN"
    if speaker != "PATIENT":
        subject, assertion, temporal = "UNKNOWN", "UNCERTAIN", "UNKNOWN"
    return assertion, subject, temporal


def _mentions(segment: TranscriptSegment) -> list[Mention]:
    matches = []
    for pattern, kind in ((_NAMES, "NAME"), (_APPEARANCE, "APPEARANCE"), (_INDICATION, "INDICATION")):
        for match in pattern.finditer(segment.text):
            assertion, subject, temporal = _attributes(
                _context(segment.text, match.start(), match.end()), segment.speaker
            )
            matches.append(Mention(
                raw_text=match.group(), start=match.start(), end=match.end(), kind=kind,
                assertion=assertion, subject=subject, temporal=temporal,
                confidence_basis="Literal demo-vocabulary match; contextual attributes are heuristic and uncalibrated.",
                clarification="Clinician: verify whose medicine this is, the product name or packaging, and whether it is currently taken.",
            ))
    return sorted(matches, key=lambda mention: (mention.start, mention.end))


def detect_mentions(segment: TranscriptSegment) -> ListenerResult:
    """Extract unconfirmed transcript mentions without external calls or state changes."""
    limitations = list(_LIMITATIONS)
    if not segment.is_final:
        limitations.append("Partial transcript: deferred analysis until a finalized segment is supplied.")
    return ListenerResult(
        event_id=segment.event_id, consultation_id=segment.consultation_id,
        segment_id=segment.segment_id, revision=segment.revision, sequence=segment.sequence,
        status="ANALYZED" if segment.is_final else "PROVISIONAL",
        mentions=_mentions(segment) if segment.is_final else [], limitations=limitations,
    )
