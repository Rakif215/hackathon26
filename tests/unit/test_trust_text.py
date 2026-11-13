"""Trust-text checks on the Demo_Fixture's Curated_Text (offline: no network, no database).

No Curated_Text value may contain a trust word, and no Curated_Text value other than an utterance may
contain a Banned_Phrase_List phrase; each failure names the JSON path and the matched word or phrase.
Requirements 14.1, 14.2, 14.4, 14.5 and 14.6.
"""

import copy
import json
from pathlib import Path

import pytest
from trust_rules import (
    BANNED_PHRASES,
    DIAGNOSIS,
    DOSE_CHANGE,
    PRESCRIBING,
    SCHEDULE_TEXTS,
    START_OR_STOP,
    TRUST_WORDS,
    banned_phrase_violations,
    banned_phrases,
    describe,
    trust_word_violations,
    whole_word_matches,
)

from hackathon26.demo_fixture import DemoFixture, curated_text, load_fixture

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "data" / "demo" / "demo_fixture.json"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fx() -> DemoFixture:
    return load_fixture(FIXTURE_PATH)


def _mutated(raw: dict, mutate) -> DemoFixture:
    data = copy.deepcopy(raw)
    mutate(data)
    return DemoFixture.model_validate_json(json.dumps(data))


# --- curated_text() --------------------------------------------------------------------------------


def test_curated_text_lists_the_team_authored_values(fx: DemoFixture) -> None:
    items = list(curated_text(fx))
    by_path = {path: (value, is_utterance)
               for path, value, is_utterance in items}
    assert len(by_path) == len(items), "a JSON path is listed twice"

    assert by_path["patient.display_name"] == ("Patient A (72F)", False)
    assert by_path["consultation.clinician"] == ("Dr. Vogel", False)
    assert by_path["consultation.scenario"] == ("hf-follow-up-v1", False)
    for i, u in enumerate(fx.utterances):
        assert by_path[f"utterances[{i}].text"] == (u.text, True)
    for i, a in enumerate(fx.appearances):
        assert by_path[f"appearances[{i}].src_name"] == (a.src_name, False)
    for i, s in enumerate(fx.class_synonyms):
        assert by_path[f"class_synonyms[{i}].synonym"] == (s.synonym, False)
    for i, r in enumerate(fx.risk_rules):
        assert by_path[f"risk_rules[{i}].rule_name"] == (r.rule_name, False)
        assert by_path[f"risk_rules[{i}].rationale"] == (r.rationale, False)

    # only utterance texts are flagged as utterances
    assert {p for p, (_, u) in by_path.items() if u} == {
        f"utterances[{i}].text" for i in range(len(fx.utterances))}


def test_curated_text_excludes_quotes_diagnosis_strength_and_schedule(fx: DemoFixture) -> None:
    paths = [path for path, _, _ in curated_text(fx)]
    for path in paths:
        assert not path.endswith(
            (".evidence_quote", ".primary_dx", ".strength", ".schedule_text")), path
    values = {value for _, value, _ in curated_text(fx)}
    assert fx.patient.primary_dx not in values
    for rule in fx.risk_rules:
        assert rule.evidence_quote not in values


# --- the committed fixture -------------------------------------------------------------------------


def test_no_curated_text_contains_a_trust_word(fx: DemoFixture) -> None:
    violations = trust_word_violations(curated_text(fx))
    assert not violations, "trust word in Curated_Text:\n" + \
        describe(violations)


def test_no_non_utterance_curated_text_contains_a_banned_phrase(fx: DemoFixture) -> None:
    violations = banned_phrase_violations(curated_text(fx))
    assert not violations, "banned phrase in Curated_Text:\n" + \
        describe(violations)


def test_a_trust_word_is_reported_with_its_path_and_word(raw: dict) -> None:
    def mutate(data: dict) -> None:
        data["risk_rules"][0]["rationale"] += " Safety is not implied."
        data["utterances"][9]["text"] = "Of course, if it is safe."

    violations = trust_word_violations(curated_text(_mutated(raw, mutate)))
    assert sorted(violations) == [
        ("risk_rules[0].rationale", "safety"), ("utterances[9].text", "safe")]
    report = describe(violations)
    assert "risk_rules[0].rationale" in report and "'safety'" in report


def test_a_banned_phrase_is_reported_outside_utterances_only(raw: dict) -> None:
    def mutate(data: dict) -> None:
        data["risk_rules"][2]["rationale"] += " Stop taking the ACE inhibitor."
        data["utterances"][0]["text"] = "Good morning. You have been well, I hope?"

    violations = banned_phrase_violations(curated_text(_mutated(raw, mutate)))
    assert violations == [("risk_rules[2].rationale", "stop taking")]
    assert "risk_rules[2].rationale: contains 'stop taking'" in describe(
        violations)


# --- the Banned_Phrase_List ------------------------------------------------------------------------


def test_banned_phrase_list_has_four_categories_of_at_least_two_phrases() -> None:
    assert set(BANNED_PHRASES) == {DOSE_CHANGE,
                                   START_OR_STOP, DIAGNOSIS, PRESCRIBING}
    for category, phrases in BANNED_PHRASES.items():
        assert len(phrases) >= 2, category
        assert all(p and p == p.strip() for p in phrases), category
    # every phrase belongs to exactly one category
    all_phrases = [phrase.casefold() for _, phrase in banned_phrases()]
    assert len(all_phrases) == len(set(all_phrases))


@pytest.mark.parametrize("schedule", SCHEDULE_TEXTS)
def test_no_banned_phrase_matches_a_schedule_text(schedule: str) -> None:
    assert whole_word_matches(schedule, [p for _, p in banned_phrases()]) == []


def test_the_schedule_texts_are_the_required_ones() -> None:
    assert SCHEDULE_TEXTS == (
        "once a day", "twice a day", "three times a day", "in the morning", "with breakfast")


# --- the checks reject and accept samples ----------------------------------------------------------


def _one(text: str, is_utterance: bool = False) -> list[tuple[str, str, bool]]:
    return [("sample", text, is_utterance)]


@pytest.mark.parametrize("word", TRUST_WORDS)
def test_trust_word_check_rejects_each_trust_word(word: str) -> None:
    assert trust_word_violations(_one(f"This combination is {word} for her.")) == [
        ("sample", word)]
    # utterances are checked for trust words too
    assert trust_word_violations(_one(f"Is it {word}?", is_utterance=True)) == [
        ("sample", word)]


@pytest.mark.parametrize("category, sample", [
    (DOSE_CHANGE, "Consider whether to reduce the dose of ramipril."),
    (START_OR_STOP, "She should stop taking ibuprofen."),
    (DIAGNOSIS, "The patient is diagnosed with acute kidney injury."),
    (PRESCRIBING, "We recommend paracetamol instead."),
])
def test_banned_phrase_check_rejects_a_sample_for_each_category(category: str, sample: str) -> None:
    violations = banned_phrase_violations(_one(sample))
    assert len(violations) == 1
    _, phrase = violations[0]
    assert phrase in BANNED_PHRASES[category]


def test_checks_accept_no_documented_interaction_found() -> None:
    sample = _one("no documented interaction found")
    assert trust_word_violations(sample) == []
    assert banned_phrase_violations(sample) == []


def test_whole_word_rule_examples() -> None:
    assert whole_word_matches("Safety", TRUST_WORDS) == ["safety"]
    assert whole_word_matches("safe,", TRUST_WORDS) == ["safe"]
    assert whole_word_matches("unsafe", TRUST_WORDS) == []
    assert whole_word_matches("safeguard", TRUST_WORDS) == []
    assert whole_word_matches("unsafe, but SAFE.", TRUST_WORDS) == ["safe"]
    assert whole_word_matches("STOP TAKING it", ["stop taking"]) == [
        "stop taking"]
    assert whole_word_matches("nonstop taking", ["stop taking"]) == []
