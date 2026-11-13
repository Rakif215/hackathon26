"""Trust-text rules for the Demo_Fixture's Curated_Text (Requirement 14). A test helper, not a test file.

- `TRUST_WORDS`: words that imply safety. No Curated_Text value may contain one (14.1).
- `BANNED_PHRASES`: the Banned_Phrase_List. Every phrase belongs to exactly one of four categories, each
  with at least two phrases (14.4). No Curated_Text value other than an utterance may contain one (14.2).
- `whole_word_matches`: the whole-word matcher both checks use. It ignores letter case and requires each
  match to be bounded at both ends by the start or end of the text or by a character for which
  `str.isalnum()` is false. Under this rule "Safety" and "safe," match and "unsafe" does not.

The phrases are chosen so that none matches a schedule text such as "once a day" or "with breakfast"
(14.5): those are instructions the patient already has, not advice from MedGuard.
"""

import re
from collections.abc import Iterable

TRUST_WORDS: tuple[str, ...] = ("safe", "safely", "safer", "safest", "safety")

DOSE_CHANGE = "dose change"
START_OR_STOP = "starting or stopping a medicine"
DIAGNOSIS = "diagnosis statement"
PRESCRIBING = "prescribing recommendation"

BANNED_PHRASES: dict[str, tuple[str, ...]] = {
    DOSE_CHANGE: (
        "increase the dose",
        "reduce the dose",
        "lower the dose",
        "double the dose",
        "halve the dose",
        "adjust the dose",
    ),
    START_OR_STOP: (
        "stop taking",
        "start taking",
        "discontinue",
        "should be stopped",
        "should be started",
    ),
    DIAGNOSIS: (
        "you have",
        "diagnosed with",
        "the diagnosis is",
        "is suffering from",
    ),
    PRESCRIBING: (
        "we recommend",
        "should prescribe",
        "should be prescribed",
        "switch to",
        "the recommended treatment",
    ),
}

SCHEDULE_TEXTS: tuple[str, ...] = (
    "once a day", "twice a day", "three times a day", "in the morning", "with breakfast")


def banned_phrases() -> list[tuple[str, str]]:
    """Every (category, phrase) pair of the Banned_Phrase_List."""
    return [(category, phrase) for category, phrases in BANNED_PHRASES.items() for phrase in phrases]


def _bounded(text: str, start: int, end: int) -> bool:
    return (start == 0 or not text[start - 1].isalnum()) and (end == len(text) or not text[end].isalnum())


def whole_word_matches(text: str, phrases: Iterable[str]) -> list[str]:
    """The phrases that occur in `text` as a whole-word, case-insensitive match, in the given order."""
    found: list[str] = []
    for phrase in phrases:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        pos = 0
        while (match := pattern.search(text, pos)) is not None:
            if _bounded(text, match.start(), match.end()):
                found.append(phrase)
                break
            pos = match.start() + 1
    return found


def trust_word_violations(items: Iterable[tuple[str, str, bool]]) -> list[tuple[str, str]]:
    """(json_path, matched word) for every Curated_Text value holding a trust word (14.1)."""
    return [(path, word) for path, value, _ in items for word in whole_word_matches(value, TRUST_WORDS)]


def banned_phrase_violations(items: Iterable[tuple[str, str, bool]]) -> list[tuple[str, str]]:
    """(json_path, matched phrase) for every non-utterance Curated_Text value holding a banned phrase (14.2)."""
    phrases = [phrase for _, phrase in banned_phrases()]
    return [(path, phrase)
            for path, value, is_utterance in items if not is_utterance
            for phrase in whole_word_matches(value, phrases)]


def describe(violations: list[tuple[str, str]]) -> str:
    """One line per violation: the Demo_Fixture field and the matched word or phrase."""
    return "\n".join(f"{path}: contains {matched!r}" for path, matched in violations)
