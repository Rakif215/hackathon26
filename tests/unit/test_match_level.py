"""Match_Level vocabulary: ranks, labels, exact lookup and single source (Requirements 1.9, 1.10)."""

import ast
from pathlib import Path

import pytest

from hackathon26.match_level import MatchLevel, UnknownMatchLevel, label, rank

EXPECTED = [
    ("NAME_MATCH", 1, "name match"),
    ("COLOUR_SHAPE_MATCH", 2, "colour + shape match"),
    ("COLOUR_MATCH", 3, "colour match"),
    ("CLASS_INFERRED", 4, "class inferred"),
    ("UNRESOLVED", 5, "unresolved"),
]

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "hackathon26"


@pytest.mark.parametrize(("code", "expected_rank", "expected_label"), EXPECTED)
def test_each_code_maps_to_rank_and_glossary_label(code, expected_rank, expected_label):
    assert rank(code) == expected_rank
    assert label(code) == expected_label
    assert rank(MatchLevel(code)) == expected_rank
    assert label(MatchLevel(code)) == expected_label


def test_enum_has_exactly_the_five_codes_in_rank_order():
    assert [member.value for member in MatchLevel] == [
        code for code, _, _ in EXPECTED]
    assert all(member.name == member.value for member in MatchLevel)


@pytest.mark.parametrize(
    "value",
    [" NAME_MATCH", "NAME_MATCH ", "name_match", "Name_Match", "\tUNRESOLVED\n", "", "NAME MATCH",
     "name match", "CONFIDENCE", "0.52"],
)
@pytest.mark.parametrize("lookup", [rank, label])
def test_non_members_raise_and_name_the_value(lookup, value):
    with pytest.raises(UnknownMatchLevel) as excinfo:
        lookup(value)
    assert repr(value) in str(excinfo.value)


def test_unknown_match_level_is_a_value_error():
    assert issubclass(UnknownMatchLevel, ValueError)


# "UNRESOLVED" is also a value of the separate resolution *status* vocabulary
# (CANDIDATES / UNRESOLVED / CONTEXT_REVIEW), so a bare "UNRESOLVED" literal is not
# evidence of a duplicated Match_Level definition. The scan looks for the other four codes.
_SCANNED_CODES = {code for code, _, _ in EXPECTED} - {"UNRESOLVED"}


def _match_level_literals_outside_vocabulary_module() -> list[str]:
    hits = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path == PACKAGE_ROOT / "match_level.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in _SCANNED_CODES:
                hits.append(
                    f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}: {node.value!r}")
    return hits


def test_match_level_codes_are_only_spelled_in_match_level_module():
    assert _match_level_literals_outside_vocabulary_module() == []
