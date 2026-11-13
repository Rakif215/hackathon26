"""Property-based tests for the Quote_Verifier (hackathon26.evidence.verify_quote).

The fixed example cases for Requirement 11 criteria 4 and 5 live in test_evidence.py; these tests
generalise them over generated, mostly non-ASCII text.
"""

from hypothesis import assume, event, given, settings
from hypothesis import strategies as st

from hackathon26.evidence import verify_quote

EXAMPLES = settings(max_examples=200, deadline=None)

# Whitespace the perturbations insert or swap: ASCII, line breaks and Unicode spaces.
WHITESPACE = [" ", "\t", "\n", "\r", "\u00a0", "\u2003", "\u3000"]
STRAIGHT_TO_TYPOGRAPHIC = {
    "'": ["\u2018", "\u2019"], '"': ["\u201c", "\u201d"]}
TYPOGRAPHIC_TO_STRAIGHT = {"\u2018": "'",
                           "\u2019": "'", "\u201c": '"', "\u201d": '"'}
QUOTE_MARKS = set(STRAIGHT_TO_TYPOGRAPHIC) | set(TYPOGRAPHIC_TO_STRAIGHT)

# Weighted toward characters the perturbations act on: cased letters in several scripts,
# whitespace and both kinds of quotation mark, plus combining marks and astral characters.
CURATED = list("aZéÉßñÑøΩωДжİı") + WHITESPACE + sorted(QUOTE_MARKS) + [
    "\u0301", "💊", "µ", "ﬁ", "-", ".", ",", "1",
]
CHARS = st.one_of(st.sampled_from(CURATED),
                  st.characters(exclude_categories=("Cs",)))
TEXTS = st.text(CHARS, min_size=1, max_size=80).filter(
    lambda s: any(ord(c) > 127 for c in s) and not s.isspace()
)


@st.composite
def nonblank_slices(draw, text=TEXTS):
    """Draw (S, i, j) with S[i:j] holding at least one non-whitespace character."""
    s = draw(text)
    anchor = draw(st.sampled_from(
        [k for k, c in enumerate(s) if not c.isspace()]))
    i = draw(st.integers(0, anchor))
    j = draw(st.integers(anchor + 1, len(s)))
    return s, i, j


# Removing leading or trailing whitespace is not listed: trimming the edge of a substring of S always
# leaves a substring of S, which Property 1 requires to verify. Removal is covered internally instead.
PERTURBATIONS = [
    "add_leading_ws", "add_trailing_ws", "insert_internal_ws", "remove_internal_ws",
    "replace_internal_ws", "flip_case", "swap_quote_mark",
]
CASED = st.one_of(
    st.sampled_from([c for c in CURATED if c.swapcase() != c]),
    st.characters(exclude_categories=("Cs",)).filter(
        lambda c: c.swapcase() != c),
)
NONBLANK = st.text(CHARS, min_size=1, max_size=20).filter(
    lambda s: not s.isspace())
ANY_TEXT = st.text(CHARS, max_size=30)


@st.composite
def perturbed_quotes(draw):
    """Draw (S, Q): Q is a real substring of S with one Requirement 11.5 difference, and Q is not in S.

    The perturbation is chosen first and the substring is built so that it applies, so every kind
    is exercised in every run.
    """
    kind = draw(st.sampled_from(PERTURBATIONS))
    ws = st.sampled_from(WHITESPACE)
    core = draw(NONBLANK)

    if kind == "add_leading_ws":
        sub, q = core, draw(ws) + core
    elif kind == "add_trailing_ws":
        sub, q = core, core + draw(ws)
    elif kind == "insert_internal_ws":
        assume(len(core) >= 2)
        k = draw(st.integers(1, len(core) - 1))
        sub, q = core, core[:k] + draw(ws) + core[k:]
    elif kind in ("remove_internal_ws", "replace_internal_ws"):
        head, tail, w = draw(NONBLANK), draw(NONBLANK), draw(ws)
        sub = head + w + tail
        other = "" if kind == "remove_internal_ws" else draw(
            ws.filter(lambda x: x != w))
        q = head + other + tail
    elif kind == "flip_case":
        head, tail, c = draw(ANY_TEXT), draw(ANY_TEXT), draw(CASED)
        sub, q = head + c + tail, head + c.swapcase() + tail
    else:  # swap_quote_mark
        head, tail, mark = draw(ANY_TEXT), draw(ANY_TEXT), draw(
            st.sampled_from(sorted(QUOTE_MARKS)))
        replacement = (
            draw(st.sampled_from(STRAIGHT_TO_TYPOGRAPHIC[mark]))
            if mark in STRAIGHT_TO_TYPOGRAPHIC
            else TYPOGRAPHIC_TO_STRAIGHT[mark]
        )
        sub, q = head + mark + tail, head + replacement + tail

    s = draw(ANY_TEXT) + sub + draw(ANY_TEXT)
    assume(any(ord(c) > 127 for c in s))
    assume(q not in s)
    event(kind)
    return s, q


# Feature: demo-data-foundation, Property 1: Every non-blank substring verifies
@EXAMPLES
@given(nonblank_slices())
def test_every_nonblank_substring_verifies(case):
    """**Validates: Requirements 11.1, 11.2, 17.2**"""
    s, i, j = case
    assert verify_quote(s[i:j], s) is True


# Feature: demo-data-foundation, Property 2: Anything that is not an exact substring is rejected
@EXAMPLES
@given(perturbed_quotes())
def test_perturbed_substring_is_rejected(case):
    """Whitespace, case and quote-mark perturbations of a real substring.

    **Validates: Requirements 11.1, 11.3, 11.5, 17.2**
    """
    s, q = case
    assert verify_quote(q, s) is False


# Feature: demo-data-foundation, Property 2: Anything that is not an exact substring is rejected
@EXAMPLES
@given(TEXTS, st.text(CHARS, min_size=1, max_size=20))
def test_arbitrary_non_substring_is_rejected(s, q):
    """**Validates: Requirements 11.1, 11.3, 17.2**"""
    assume(q not in s)
    assert verify_quote(q, s) is False


# Feature: demo-data-foundation, Property 2: Anything that is not an exact substring is rejected
@EXAMPLES
@given(TEXTS, st.text(st.sampled_from(WHITESPACE), max_size=6))
def test_empty_or_whitespace_only_quote_is_rejected(s, q):
    """Empty and whitespace-only quotes fail even when they occur in S.

    **Validates: Requirements 11.1, 11.4, 17.2**
    """
    assert verify_quote(q, s) is False
    assert verify_quote(q, s + q) is False


# Feature: demo-data-foundation, Property 2: Anything that is not an exact substring is rejected
@EXAMPLES
@given(st.one_of(st.none(), st.text(CHARS, max_size=20)))
def test_any_quote_against_null_text_is_rejected(q):
    """**Validates: Requirements 11.1, 11.4, 17.2**"""
    assert verify_quote(q, None) is False
