"""Unit tests for the Demo_Fixture validator `fixture_problems` (offline: no network, no database).

The committed fixture plus the committed Label_Snapshots must give no problem. Each hand-written
mutation of the committed fixture must give a `Problem` naming the mutated JSON path and the
requirement it breaks. Requirements 4.6, 4.7, 4.9, 4.10, 5.4-5.6, 5.8, 6.2-6.11, 8.11, 9.1, 9.8, 9.9,
9.11, 9.12, 10.6, 11.7, 17.4 and 17.7.
"""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

import hackathon26.demo_fixture as demo_fixture
from hackathon26.demo_fixture import Problem, evidence_sections, fixture_problems, load_fixture
from hackathon26.evidence import verify_quote
from hackathon26.labels import content_hash, load_label, load_manifest

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "data" / "demo" / "demo_fixture.json"
MANIFEST_PATH = REPO / "data" / "reference" / "label_manifest.json"
LABEL_DIR = REPO / "data" / "reference" / "labels"
RAMIPRIL_SET_ID = "01da05d8-e72e-4208-bf92-a5cd929f15ab"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST_PATH)


@pytest.fixture(scope="module")
def labels(manifest):
    # load_label raises LabelError naming the drug, so a missing snapshot fails the test (17.7)
    return [load_label(entry, LABEL_DIR) for entry in manifest]


def _mutated(tmp_path: Path, raw: dict, mutate) -> "demo_fixture.DemoFixture":
    data = copy.deepcopy(raw)
    mutate(data)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_fixture(path)


def _has(problems: list[Problem], field: str, requirement: str) -> bool:
    return any(p.field == field and p.requirement == requirement for p in problems)


def _assert_problem(problems: list[Problem], field: str, requirement: str) -> Problem:
    assert _has(problems, field,
                requirement), f"no ({field}, {requirement}) in {problems}"
    return next(p for p in problems if p.field == field and p.requirement == requirement)


# --- The committed inputs are clean ---


def test_committed_fixture_and_snapshots_give_no_problem(labels, manifest):
    assert fixture_problems(load_fixture(FIXTURE_PATH), labels, manifest) == []


def test_evidence_sections_index_the_committed_snapshots(labels, manifest):
    sections = evidence_sections(labels, manifest)
    interactions = sections[("ramipril", "drug_interactions", 0)]
    cautions = sections[("ramipril", "warnings_and_cautions", 0)]
    assert (interactions.section_id, cautions.section_id) == (1500, 1400)
    for (drug, field, element), row in sections.items():
        assert (row.generic_name, row.section_type,
                row.element) == (drug, field, element)
        assert row.text == next(
            lb for lb in labels if lb.entry.generic_name == drug).label[field][element]
        assert row.content_sha256 == content_hash(row.text)


def test_rule_quotes_verify_against_their_sections(labels, manifest):
    """Requirement 17.7: every Evidence_Quote checked with the Quote_Verifier, naming rule, set id, section."""
    sections = evidence_sections(labels, manifest)
    set_ids = {e.generic_name: e.set_id for e in manifest}
    for rule in load_fixture(FIXTURE_PATH).risk_rules:
        ev = rule.evidence
        section = sections[(ev.drug, ev.field, ev.element)]
        assert verify_quote(rule.evidence_quote, section.text), (
            f"{rule.rule_name}: quote not in {set_ids[ev.drug]} {ev.field}")


def test_validator_uses_the_shared_quote_verifier():
    """Requirement 11.7: one Quote_Verifier for the seed, the join check and the tests."""
    assert demo_fixture.verify_quote is verify_quote


# --- Hand-written mutations: (mutation, mutated JSON path, requirement) ---


def _set(*path_and_value):
    *path, value = path_and_value

    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _edit_text(index, old, new):
    def mutate(data):
        text = data["utterances"][index]["text"]
        assert old in text
        data["utterances"][index]["text"] = text.replace(old, new, 1)
    return mutate


MUTATIONS = [
    # Requirement 4.10: unknown drug
    ("medication names an unknown drug", _set("medications", 1, "drug", "warfarin"),
     "medications[1].drug", "4.10"),
    ("appearance names an unknown drug", _set("appearances", 2, "drug", "warfarin"),
     "appearances[2].drug", "4.10"),
    # Requirements 4.6, 4.7: colour, schedule, shape
    ("furosemide turned yellow", _set("appearances", 2,
     "color", "yellow"), "appearances[2].color", "4.6"),
    ("metoprolol turned white", _set("appearances", 1,
     "color", "white"), "appearances[1].color", "4.6"),
    ("furosemide schedule differs", _set("medications", 2, "schedule_text", "in the evening"),
     "medications[2].schedule_text", "4.6"),
    ("ramipril schedule differs", _set("medications", 0, "schedule_text", "at night"),
     "medications[0].schedule_text", "4.6"),
    ("furosemide shape equals ramipril", _set("appearances",
     2, "shape", "round"), "appearances[2].shape", "4.7"),
    # Requirement 5.4: lab completeness and range
    ("null lab value", _set("labs", 4, "value_num", None),
     "labs[4].value_num", "5.4"),
    ("null lab unit", _set("labs", 1, "unit", None), "labs[1].unit", "5.4"),
    ("no reference bound", _set("labs", 0,
     "ref_low", None), "labs[0].ref_low", "5.4"),
    ("REF_LOW equals REF_HIGH", _set("labs", 7,
     "ref_low", "5.0"), "labs[7].ref_low", "5.4"),
    ("REF_HIGH below REF_LOW", _set("labs", 3,
     "ref_high", "0.40"), "labs[3].ref_high", "5.4"),
    # Requirement 5.5: date window
    ("lab after as_of", _set("labs", 2, "measured_at",
     "2026-11-14"), "labs[2].measured_at", "5.5"),
    ("lab 365 days before as_of", _set("labs", 6, "measured_at",
     "2025-11-13"), "labs[6].measured_at", "5.5"),
    # Requirement 5.6: distinct dates and trend
    ("duplicate lab date", _set("labs", 5, "measured_at",
     "2026-07-16"), "labs[5].measured_at", "5.6"),
    ("eGFR rises", _set("labs", 1, "value_num", "70"),
     "labs[1].value_num", "5.6"),
    ("creatinine falls", _set("labs", 3, "value_num", "1.08"),
     "labs[3].value_num", "5.6"),
    # Requirement 5.8: latest value inside its range
    ("latest potassium inside range", _set("labs", 8,
     "value_num", "4.95"), "labs[8].value_num", "5.8"),
    ("latest eGFR inside range", _set("labs", 2,
     "value_num", "60"), "labs[2].value_num", "5.8"),
    # Requirement 6.2: speakers
    ("speaker swap", _set("utterances", 4, "speaker",
     "PATIENT"), "utterances[4].speaker", "6.2"),
    # Requirement 6.6: SEQ
    ("SEQ duplicate", _set("utterances", 6,
     "seq", 6), "utterances[6].seq", "6.6"),
    ("SEQ gap", _set("utterances", 9, "seq", 11), "utterances[9].seq", "6.6"),
    # Requirements 6.3, 6.4, 6.9: required phrases are case-sensitive
    ("phrase in the wrong case", _edit_text(1, "the small yellow one", "the Small yellow one"),
     "utterances[1].text", "6.3"),
    ("long white phrase in the wrong case", _edit_text(3, "the long white one", "The long white one"),
     "utterances[3].text", "6.3"),
    ("knee phrase in the wrong case", _edit_text(5, "something for my knee", "Something for my knee"),
     "utterances[5].text", "6.4"),
    ("anchor phrase in the wrong case", _edit_text(8, "bring the box", "Bring the box"),
     "utterances[8].text", "6.9"),
    # Requirement 6.5: drug names
    ("drug name inserted", _edit_text(4, "Has anything", "Is the Ramipril fine? Has anything"),
     "utterances[4].text", "6.5"),
    ("ibuprofen outside SEQ 8", _edit_text(6, "called?",
     "called, the IBUPROFEN?"), "utterances[6].text", "6.5"),
    ("ibuprofen missing from SEQ 8", _edit_text(
        7, "ibuprofen", "something"), "utterances[7].text", "6.5"),
    # Requirement 6.7: offsets
    ("offset step below 2000", _set("utterances", 3,
     "offset_ms", 16999), "utterances[3].offset_ms", "6.7"),
    ("first offset not zero", _set("utterances", 0,
     "offset_ms", 1000), "utterances[0].offset_ms", "6.7"),
    ("last offset above 90000", _set("utterances", 9,
     "offset_ms", 90001), "utterances[9].offset_ms", "6.7"),
    # Requirement 6.10: text length and content
    ("whitespace-only text", _set("utterances", 9,
     "text", " \t "), "utterances[9].text", "6.10"),
    ("4001-character text", _set("utterances", 9,
     "text", "a" * 4001), "utterances[9].text", "6.10"),
    # Requirement 6.11: digits and dose wording
    ("digit in text", _edit_text(2, "Good.", "Good, 2 of them."),
     "utterances[2].text", "6.11"),
    ("mg in text", _edit_text(9, "Of course.",
     "Of course, the MG ones."), "utterances[9].text", "6.11"),
    ("twice a day in text", _edit_text(7, "I'm not sure.",
     "I take it twice a day."), "utterances[7].text", "6.11"),
    # Requirements 9.8, 9.9 (reported per 9.12)
    ("required class in the wrong case", _set("risk_rules", 0, "required_classes", 0, "nsaid"),
     "risk_rules[0].required_classes[0]", "9.9"),
    ("unknown required class", _set("risk_rules", 1, "required_classes", 2, "thiazide diuretic"),
     "risk_rules[1].required_classes[2]", "9.9"),
    ("not-seeded optional class", _set("risk_rules", 2, "required_classes", 0, "potassium-sparing diuretic"),
     "risk_rules[2].required_classes[0]", "9.9"),
    ("ungrounded required class", _set("risk_rules", 2, "required_classes", 0, "beta blocker"),
     "risk_rules[2].required_classes[0]", "9.8"),
    # Requirement 10.6: quote altered by one character
    ("quote with one character changed",
     lambda d: d["risk_rules"][0].update(evidence_quote=d["risk_rules"][0]["evidence_quote"].replace(
         "elderly", "elderlY", 1)),
     "risk_rules[0].evidence_quote", "10.6"),
    ("evidence section does not exist", _set("risk_rules", 2, "evidence", "element", 7),
     "risk_rules[2].evidence", "10.6"),
    # Requirement 8.11: over-length values
    ("over-length display name", _set("patient", "display_name",
     "P" * 101), "patient.display_name", "8.11"),
    ("over-length manufacturer", _set("appearances", 0, "manufacturer", "M" * 201),
     "appearances[0].manufacturer", "8.11"),
    ("over-length utterance", _set("utterances", 9,
     "text", "a" * 4001), "utterances[9].text", "8.11"),
]


@pytest.mark.parametrize("mutate, field, requirement", [m[1:] for m in MUTATIONS], ids=[m[0] for m in MUTATIONS])
def test_mutation_is_reported_at_its_path(tmp_path, raw, labels, manifest, mutate, field, requirement):
    problems = fixture_problems(
        _mutated(tmp_path, raw, mutate), labels, manifest)
    _assert_problem(problems, field, requirement)


def test_manufacturer_matching_a_snapshot_in_other_case(tmp_path, raw, labels, manifest):
    # 'Proficient Rx LP'
    real = labels[0].label["openfda"]["manufacturer_name"][0]
    fx = _mutated(tmp_path, raw, _set(
        "appearances", 1, "manufacturer", real.swapcase()))
    problem = _assert_problem(fixture_problems(
        fx, labels, manifest), "appearances[1].manufacturer", "4.9")
    assert real in problem.message


def test_unknown_drug_message_names_the_drug(tmp_path, raw, labels, manifest):
    fx = _mutated(tmp_path, raw, _set("medications", 1, "drug", "warfarin"))
    assert "warfarin" in _assert_problem(fixture_problems(
        fx, labels, manifest), "medications[1].drug", "4.10").message


def test_class_problems_name_rule_and_class(tmp_path, raw, labels, manifest):
    """Requirement 9.12: the problem names the RULE_NAME and the class that failed."""
    fx = _mutated(tmp_path, raw, _set("risk_rules", 2,
                  "required_classes", 0, "beta blocker"))
    message = _assert_problem(fixture_problems(fx, labels, manifest), "risk_rules[2].required_classes[0]",
                              "9.8").message
    assert "ACE inhibitor: hyperkalemia risk" in message and "beta blocker" in message


def test_quote_problem_names_rule_set_id_and_section(tmp_path, raw, labels, manifest):
    """Requirement 10.6: the problem names the RULE_NAME, LABEL_SET_ID and SECTION_TYPE."""
    fx = _mutated(tmp_path, raw, lambda d: d["risk_rules"][2].update(
        evidence_quote=d["risk_rules"][2]["evidence_quote"] + "."))
    message = _assert_problem(fixture_problems(fx, labels, manifest), "risk_rules[2].evidence_quote",
                              "10.6").message
    assert "ACE inhibitor: hyperkalemia risk" in message
    assert RAMIPRIL_SET_ID in message and "warnings_and_cautions" in message


def test_lab_swap_breaks_the_trend(tmp_path, raw, labels, manifest):
    def swap(data):
        a, b = data["labs"][6], data["labs"][7]
        a["value_num"], b["value_num"] = b["value_num"], a["value_num"]
    problems = fixture_problems(
        _mutated(tmp_path, raw, swap), labels, manifest)
    assert _has(problems, "labs[6].value_num", "5.6") and _has(
        problems, "labs[7].value_num", "5.6")


# --- Manifest / fixture drug mismatch (9.1, 9.11) ---


def test_demo_drug_missing_from_manifest(raw, labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    kept = [e for e in manifest if e.generic_name != "ibuprofen"]
    problems = fixture_problems(
        fx, [lb for lb in labels if lb.entry in kept], kept)
    assert "ibuprofen" in _assert_problem(
        problems, "drugs[3].generic_name", "9.11").message


def test_fixture_drug_not_in_manifest(tmp_path, raw, labels, manifest):
    fx = _mutated(tmp_path, raw, _set(
        "drugs", 1, "generic_name", "metoprolol tartrate"))
    problems = fixture_problems(fx, labels, manifest)
    _assert_problem(problems, "drugs[1].generic_name", "9.1")
    # and the manifest's metoprolol succinate entry now has no fixture drug
    _assert_problem(problems, "label_manifest.labels[1].generic_name", "9.1")


# --- Over-length label values (8.11) ---


def test_over_length_section_text(raw, labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    ramipril = labels[0]
    huge = replace(ramipril, label={
                   **ramipril.label, "boxed_warning": ["a" * 2_000_001]})
    problem = _assert_problem(fixture_problems(fx, [huge, *labels[1:]], manifest),
                              "labels[ramipril].boxed_warning[0]", "8.11")
    assert "ramipril" in problem.message and "SECTION_TEXT" in problem.message
    assert "2000001" in problem.message


def test_over_length_source_url(raw, labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    furosemide = labels[2]
    long_url = replace(furosemide, metadata=replace(
        furosemide.metadata, request_url="https://x/" + "u" * 500))
    problem = _assert_problem(fixture_problems(fx, [*labels[:2], long_url, labels[3]], manifest),
                              "labels[furosemide].metadata.request_url", "8.11")
    assert "SOURCE_URL" in problem.message and "furosemide" in problem.message


# --- Over-length values that build_rows assembles (8.11) ---


def _openfda(loaded, **values):
    return replace(loaded, label={**loaded.label, "openfda": {**loaded.label.get("openfda", {}), **values}})


def test_over_length_brand_names(labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    # 100 brands of 4 characters joined by ", " give 598 characters, above DRUG.BRAND_NAMES VARCHAR(500)
    many = _openfda(labels[3], brand_name=[f"B{i:03d}" for i in range(100)])
    problem = _assert_problem(fixture_problems(fx, [*labels[:3], many], manifest),
                              "labels[ibuprofen].openfda.brand_name", "8.11")
    assert "BRAND_NAMES" in problem.message and "ibuprofen" in problem.message and "598" in problem.message


def test_over_length_class_src_name(labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    # "curated; openFDA EPC: " is 22 characters, so an 79-character EPC exceeds DRUG_CLASS.SRC_NAME VARCHAR(100)
    long_epc = _openfda(labels[0], pharm_class_epc=["E" * 79])
    problem = _assert_problem(fixture_problems(fx, [long_epc, *labels[1:]], manifest),
                              "labels[ramipril].openfda.pharm_class_epc[0]", "8.11")
    assert "DRUG_CLASS.SRC_NAME" in problem.message and "101" in problem.message


def test_malformed_brand_list_is_a_problem(labels, manifest):
    fx = load_fixture(FIXTURE_PATH)
    bad = _openfda(labels[0], brand_name="Ramipril")
    _assert_problem(fixture_problems(
        fx, [bad, *labels[1:]], manifest), "labels[ramipril].openfda.brand_name", "9.10")
