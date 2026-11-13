"""The Match_Level confidence vocabulary: the single source of its codes, ranks and labels.

Confidence is a named match basis, not an uncalibrated percentage. Codes are ranked from
1 (strongest) to 5 (weakest). Lookup is exact: no whitespace stripping and no case folding.
"""

from enum import StrEnum


class MatchLevel(StrEnum):
    NAME_MATCH = "NAME_MATCH"
    COLOUR_SHAPE_MATCH = "COLOUR_SHAPE_MATCH"
    COLOUR_MATCH = "COLOUR_MATCH"
    CLASS_INFERRED = "CLASS_INFERRED"
    UNRESOLVED = "UNRESOLVED"


class UnknownMatchLevel(ValueError):
    """Raised when a value is not exactly one of the five Match_Level codes."""

    def __init__(self, value: object) -> None:
        super().__init__(f"unknown Match_Level code: {value!r}")
        self.value = value


_RANKS: dict[str, int] = {
    MatchLevel.NAME_MATCH.value: 1,
    MatchLevel.COLOUR_SHAPE_MATCH.value: 2,
    MatchLevel.COLOUR_MATCH.value: 3,
    MatchLevel.CLASS_INFERRED.value: 4,
    MatchLevel.UNRESOLVED.value: 5,
}

_LABELS: dict[str, str] = {
    MatchLevel.NAME_MATCH.value: "name match",
    MatchLevel.COLOUR_SHAPE_MATCH.value: "colour + shape match",
    MatchLevel.COLOUR_MATCH.value: "colour match",
    MatchLevel.CLASS_INFERRED.value: "class inferred",
    MatchLevel.UNRESOLVED.value: "unresolved",
}


def _key(code: object) -> str:
    # Only real strings are looked up; anything else (None, ints, bytes) is unknown.
    if not isinstance(code, str) or str(code) not in _RANKS:
        raise UnknownMatchLevel(code)
    return str(code)


def rank(code: str) -> int:
    """Return 1 (NAME_MATCH, strongest) to 5 (UNRESOLVED, weakest)."""
    return _RANKS[_key(code)]


def label(code: str) -> str:
    """Return the plain-language Glossary label for a code."""
    return _LABELS[_key(code)]
