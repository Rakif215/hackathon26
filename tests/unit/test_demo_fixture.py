"""Unit tests for the committed Demo_Fixture and its loader (offline: no network, no database).

Reads `data/demo/demo_fixture.json` itself, not a copy.
Requirements 4.1-4.5, 4.8, 5.1-5.3, 5.7, 6.1, 6.4, 6.8, 6.9, 9.1, 9.2, 9.4, 9.7, 10.1-10.5, 10.7,
10.9 and 16.4.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from hackathon26.demo_fixture import DemoFixture, FixtureError, load_fixture
from hackathon26.evidence import verify_quote
from hackathon26.labels import DEMO_DRUGS, OPTIONAL_DRUGS, load_label, load_manifest
from hackathon26.listener.detect import detect_mentions
from hackathon26.listener.models import TranscriptSegment

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "data" / "demo" / "demo_fixture.json"
MANIFEST_PATH = REPO / "data" / "reference" / "label_manifest.json"
LABEL_DIR = REPO / "data" / "reference" / "labels"

SYNONYM_CURATOR = "MedGuard team, demo-data-foundation"
APPEARANCE_SRC = "synthetic demo fixture: invented appearance, not a real product"
TRIPLE_WHAMMY = "NSAID + ACE inhibitor + loop diuretic: acute kidney injury risk"
TRIPLE_QUOTE = (
    "In patients who are elderly, volume-depleted (including those on diuretic therapy), or with "
    "compromised renal function, co-administration of NSAIDs, including selective COX-2 inhibitors, "
    "with ACE inhibitors, including ramipril, may result in deterioration of renal function, including "
    "possible acute renal failure."
)
POTASSIUM_QUOTE = (
    "Risk factors for the development of hyperkalemia include renal insufficiency, diabetes mellitus, "
    "and the concomitant use of potassium-sparing diuretics, potassium supplements, and/or "
    "potassium-containing salt substitutes"
)
RATIONALE_401 = (
    "Links the NSAID + ACE inhibitor + loop diuretic combination to the patient's dated eGFR results. "
    "The ramipril label states that NSAIDs given with ACE inhibitors to patients who are elderly, "
    "volume-depleted (including those on diuretic therapy) or have compromised renal function may cause "
    "deterioration of renal function. The eGFR trend is shown beside the quoted text for clinician review."
)
RATIONALE_403 = (
    "Links an ACE inhibitor to the patient's dated potassium results. The ramipril label lists renal "
    "insufficiency and the concomitant use of potassium-sparing diuretics, potassium supplements or "
    "potassium-containing salt substitutes as risk factors for hyperkalemia. The potassium values are "
    "shown against their stored reference range for clinician review."
)

SCRIPT = [
    (1, 501, "DOCTOR", 0, "Good morning. How have things been since July?"),
    (2, 502, "PATIENT", 5000,
     "Mostly alright. I take the white one in the morning and the small yellow one with breakfast, "
     "like you said."),
    (3, 503, "DOCTOR", 15000, "Good. And the water tablet?"),
    (4, 504, "PATIENT", 20000, "Yes, I take the long white one as well. Though I get dizzy standing up sometimes."),
    (5, 505, "DOCTOR", 30000, "We'll come back to the dizziness. Has anything else changed?"),
    (6, 506, "PATIENT", 36000, "My knee has been terrible. My GP gave me something for my knee a couple of weeks ago."),
    (7, 507, "DOCTOR", 48000, "Do you remember what it's called?"),
    (8, 508, "PATIENT", 53000, "I think the box says ibuprofen, but I'm not sure. It's a red and white box."),
    (9, 509, "DOCTOR", 65000, "Could you bring the box to the next appointment?"),
    (10, 510, "PATIENT", 72000, "Of course."),
]


@pytest.fixture(scope="module")
def fx() -> DemoFixture:
    return load_fixture(FIXTURE_PATH)


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _drug(fx: DemoFixture, name: str):
    return next(d for d in fx.drugs if d.generic_name == name)


# --- Patient, medications, appearances, labs (Requirements 4, 5, 16.4) ---


def test_as_of_and_patient(fx):
    assert fx.as_of == date(2026, 11, 13)
    p = fx.patient
    assert (p.patient_id, p.display_name, p.birth_year, p.sex, p.primary_dx, p.is_synthetic) == (
        1, "Patient A (72F)", 1954, "F", "Chronic heart failure (HFrEF)", True)


def test_three_current_medications(fx):
    meds = [(m.patient_med_id, m.drug, m.strength, m.schedule_text, m.started_on, m.stopped_on)
            for m in fx.medications]
    assert meds == [
        (201, "ramipril", "5 mg", "once in the morning", date(2024, 3, 4), None),
        (202, "metoprolol succinate", "47.5 mg", "with breakfast", date(2024, 3, 4), None),
        (203, "furosemide", "40 mg", "once in the morning", date(2025, 1, 20), None),
    ]
    assert all(m.started_on < date(2026, 5, 14) for m in fx.medications)
    assert "ibuprofen" not in {m.drug for m in fx.medications}


def test_three_appearances(fx):
    strength = {m.drug: m.strength for m in fx.medications}
    rows = [(a.drug, a.color, a.shape, a.manufacturer) for a in fx.appearances]
    assert rows == [
        ("ramipril", "white", "round", "Nordpharm (fictional)"),
        ("metoprolol succinate", "yellow", "oval", "Alpenmed (fictional)"),
        ("furosemide", "white", "oblong", "Isarpharma (fictional)"),
    ]
    for a in fx.appearances:
        assert a.imprint is None
        assert a.strength == strength[a.drug]
        assert a.src_name == APPEARANCE_SRC
        assert "synthetic" in a.src_name.lower()


def test_manufacturers_are_not_snapshot_manufacturers(fx):
    real = set()
    for entry in load_manifest(MANIFEST_PATH):
        real.update(n.casefold() for n in load_label(entry, LABEL_DIR).label["openfda"].get("manufacturer_name", []))
    assert real  # the snapshots name real manufacturers, so the check is not vacuous
    assert not {a.manufacturer.casefold() for a in fx.appearances} & real


def test_nine_labs(fx):
    d = Decimal
    rows = [(lab.lab_id, lab.analyte, lab.value_num, lab.unit, lab.ref_low, lab.ref_high, lab.measured_at)
            for lab in fx.labs]
    assert rows == [
        (301, "EGFR", d("62"), "mL/min/1.73m2", d("60"), None, date(2026, 5, 14)),
        (302, "EGFR", d("55"), "mL/min/1.73m2", d("60"), None, date(2026, 7, 16)),
        (303, "EGFR", d("48"), "mL/min/1.73m2", d("60"), None, date(2026, 10, 12)),
        (304, "CREATININE", d("0.97"), "mg/dL", d("0.50"), d("1.10"), date(2026, 5, 14)),
        (305, "CREATININE", d("1.07"), "mg/dL", d("0.50"), d("1.10"), date(2026, 7, 16)),
        (306, "CREATININE", d("1.20"), "mg/dL", d("0.50"), d("1.10"), date(2026, 10, 12)),
        (307, "POTASSIUM", d("4.6"), "mmol/L", d("3.5"), d("5.0"), date(2026, 5, 14)),
        (308, "POTASSIUM", d("4.9"), "mmol/L", d("3.5"), d("5.0"), date(2026, 7, 16)),
        (309, "POTASSIUM", d("5.1"), "mmol/L", d("3.5"), d("5.0"), date(2026, 10, 12)),
    ]
    # Decimals keep their written scale, so "1.20" is not read as a float 1.2
    assert str(fx.labs[5].value_num) == "1.20"


def test_decimals_are_json_strings(raw):
    for lab in raw["labs"]:
        for key in ("value_num", "ref_low", "ref_high"):
            assert lab[key] is None or isinstance(lab[key], str)


# --- Consultation, script, synonyms (Requirements 6, 9.7) ---


def test_consultation(fx):
    c = fx.consultation
    assert (c.consult_id, c.clinician, c.started_at, c.scenario) == (
        1, "Dr. Vogel", datetime(2026, 11, 13, 9, 0, 0), "hf-follow-up-v1")
    assert c.started_at.tzinfo is None


def test_demo_script_matches_design_table(fx):
    assert [(u.seq, u.utterance_id, u.speaker, u.offset_ms, u.text) for u in fx.utterances] == SCRIPT


def test_demo_script_anchor_phrases(fx):
    text = {u.seq: u.text for u in fx.utterances}
    assert "the white one" in text[2] and "the small yellow one" in text[2]
    assert "the long white one" in text[4] and "dizzy" in text[4]
    assert "something for my knee" in text[6]
    assert "Good morning" in text[1]
    assert "water tablet" in text[3]
    assert "bring the box" in text[9]
    assert {u.speaker for u in fx.utterances} == {"DOCTOR", "PATIENT"}


def test_listener_reads_patient_descriptions_as_current_use(fx):
    """The listener (read-only here) must take SEQ 2 and 4 as affirmed, current, the patient's own."""
    text = {u.seq: u.text for u in fx.utterances}
    for seq, phrases in ((2, {"the white one", "the small yellow one"}), (4, {"the long white one"})):
        segment = TranscriptSegment(
            schema_version="1", event_id=f"e{seq}", consultation_id="1", segment_id=f"s{seq}",
            revision=1, sequence=seq, speaker="PATIENT", text=text[seq], is_final=True,
            source="script", occurred_at="2026-11-13T09:00:00Z")
        found = {m.raw_text: m for m in detect_mentions(segment).mentions if m.kind == "APPEARANCE"}
        assert phrases <= set(found)
        for phrase in phrases:
            m = found[phrase]
            assert (m.assertion, m.subject, m.temporal) == ("AFFIRMED", "PATIENT", "CURRENT")


def test_class_synonyms(fx):
    assert [(s.class_name, s.synonym, s.curated_by) for s in fx.class_synonyms] == [
        ("NSAID", "NSAIDs", SYNONYM_CURATOR),
        ("ACE inhibitor", "ACE inhibitors", SYNONYM_CURATOR),
        ("loop diuretic", "diuretic therapy", SYNONYM_CURATOR),
    ]


# --- Drugs and classes (Requirement 9) ---


def test_six_drugs(fx):
    rows = [(d.drug_id, d.generic_name, d.rxcui, d.is_otc) for d in fx.drugs]
    assert rows == [
        (101, "ramipril", "35296", False),
        (102, "metoprolol succinate", "6918", False),
        (103, "furosemide", "4603", False),
        (104, "ibuprofen", "5640", True),
        (105, "spironolactone", "9997", False),
        (106, "potassium chloride", "8591", False),
    ]
    assert tuple(d.generic_name for d in fx.drugs) == DEMO_DRUGS + OPTIONAL_DRUGS


def test_drug_classes_are_epc(fx):
    expected = {
        "ramipril": "ACE inhibitor", "metoprolol succinate": "beta blocker", "furosemide": "loop diuretic",
        "ibuprofen": "NSAID", "spironolactone": "potassium-sparing diuretic",
        "potassium chloride": "potassium supplement",
    }
    for name, class_name in expected.items():
        classes = _drug(fx, name).classes
        assert [(c.class_name, c.class_type) for c in classes] == [(class_name, "EPC")]


# --- Risk rules (Requirement 10) ---


def test_three_risk_rules(fx):
    rules = [(r.rule_id, r.rule_name, r.analyte, r.direction, r.required_classes,
              (r.evidence.drug, r.evidence.field, r.evidence.element), r.concern_at)
             for r in fx.risk_rules]
    triple = ("NSAID", "ACE inhibitor", "loop diuretic")
    assert rules == [
        (401, TRIPLE_WHAMMY, "EGFR", "LOW", triple, ("ramipril", "drug_interactions", 0), None),
        (402, TRIPLE_WHAMMY, "CREATININE", "HIGH", triple, ("ramipril", "drug_interactions", 0), None),
        (403, "ACE inhibitor: hyperkalemia risk", "POTASSIUM", "HIGH", ("ACE inhibitor",),
         ("ramipril", "warnings_and_cautions", 0), None),
    ]


def test_risk_rule_quotes_are_verbatim(fx):
    by_id = {r.rule_id: r for r in fx.risk_rules}
    assert by_id[401].evidence_quote == TRIPLE_QUOTE
    assert by_id[402].evidence_quote == TRIPLE_QUOTE
    assert by_id[403].evidence_quote == POTASSIUM_QUOTE
    ramipril = next(e for e in load_manifest(MANIFEST_PATH) if e.generic_name == "ramipril")
    label = load_label(ramipril, LABEL_DIR).label
    for rule in fx.risk_rules:
        section = label[rule.evidence.field][rule.evidence.element]
        assert verify_quote(rule.evidence_quote, section)


def test_risk_rule_rationale(fx):
    by_id = {r.rule_id: r for r in fx.risk_rules}
    assert by_id[401].rationale == RATIONALE_401
    assert by_id[402].rationale == RATIONALE_401.replace("eGFR", "creatinine")
    assert by_id[403].rationale == RATIONALE_403
    analyte_word = {"EGFR": "egfr", "CREATININE": "creatinine", "POTASSIUM": "potassium"}
    for rule in fx.risk_rules:
        assert 0 < len(rule.rationale) <= 1000
        text = rule.rationale.lower()
        assert analyte_word[rule.analyte] in text
        assert all(c.lower() in text for c in rule.required_classes)


# --- Loader strictness ---


def test_fixture_is_frozen(fx):
    with pytest.raises(ValidationError):
        fx.patient.display_name = "x"


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _rejects(tmp_path: Path, data: dict, json_path: str) -> FixtureError:
    with pytest.raises(FixtureError) as info:
        load_fixture(_write(tmp_path, data))
    assert json_path in info.value.paths
    assert json_path in str(info.value)
    return info.value


def test_unknown_key_is_rejected_with_path(tmp_path, raw):
    data = json.loads(json.dumps(raw))
    data["patient"]["nickname"] = "Anna"
    _rejects(tmp_path, data, "patient.nickname")
    data = json.loads(json.dumps(raw))
    data["extra_section"] = []
    _rejects(tmp_path, data, "extra_section")


def test_empty_string_is_rejected_with_path(tmp_path, raw):
    data = json.loads(json.dumps(raw))
    data["utterances"][3]["text"] = ""
    _rejects(tmp_path, data, "utterances[3].text")


def test_float_decimal_is_rejected_with_path(tmp_path, raw):
    data = json.loads(json.dumps(raw))
    data["labs"][3]["value_num"] = 0.97
    _rejects(tmp_path, data, "labs[3].value_num")


@pytest.mark.parametrize("value, path", [
    ("2026-05-14T00:00:00", "labs[0].measured_at"),
    ("14.05.2026", "labs[0].measured_at"),
])
def test_date_must_be_iso_day(tmp_path, raw, value, path):
    data = json.loads(json.dumps(raw))
    data["labs"][0]["measured_at"] = value
    _rejects(tmp_path, data, path)


@pytest.mark.parametrize("value", ["2026-11-13T09:00:00Z", "2026-11-13T09:00:00+01:00", "2026-11-13 09:00:00"])
def test_start_time_has_no_zone(tmp_path, raw, value):
    data = json.loads(json.dumps(raw))
    data["consultation"]["started_at"] = value
    _rejects(tmp_path, data, "consultation.started_at")


def test_invalid_json_and_missing_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(FixtureError):
        load_fixture(bad)
    with pytest.raises(FixtureError):
        load_fixture(tmp_path / "missing.json")
