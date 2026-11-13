"""Unit tests for `build_rows` and `to_wire` (offline: no network, no database).

Builds the seed rows from the committed Demo_Fixture, Label_Manifest, Label_Snapshots and Snapshot_Metadata,
and checks them against the Schema_File (`sql/01_schema.sql`) and the design's expected row counts.
Requirements 3.3, 3.4, 3.5, 3.9, 4.5, 8.6, 9.1, 9.3, 9.5, 9.6, 9.10, 10.4, 10.5, 10.8, 10.10 and 17.5.
"""

import ast
import hashlib
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import hackathon26.demo_fixture as demo_fixture
from hackathon26.demo_fixture import SEED_OWNED_TABLES, build_rows, load_fixture, to_wire
from hackathon26.evidence import verify_quote
from hackathon26.labels import import_sections, load_label, load_manifest
from hackathon26.schema_file import parse_tables

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "data" / "demo" / "demo_fixture.json"
MANIFEST_PATH = REPO / "data" / "reference" / "label_manifest.json"
LABEL_DIR = REPO / "data" / "reference" / "labels"
SCHEMA_PATH = REPO / "sql" / "01_schema.sql"
RAMIPRIL_SET_ID = "01da05d8-e72e-4208-bf92-a5cd929f15ab"

EXPECTED_TABLES = (
    "DRUG", "DRUG_CLASS", "CLASS_SYNONYM", "DRUG_LABEL_SECTION", "DRUG_APPEARANCE", "PATIENT",
    "PATIENT_MEDICATION", "LAB_RESULT", "RISK_LAB_RULE", "RISK_RULE_CLASS", "CONSULTATION", "UTTERANCE",
)
# Design "Expected row counts after a seed run"; DRUG_LABEL_SECTION is checked separately.
EXPECTED_COUNTS = {
    "DRUG": 4, "DRUG_CLASS": 4, "CLASS_SYNONYM": 3, "DRUG_APPEARANCE": 3, "PATIENT": 1,
    "PATIENT_MEDICATION": 3, "LAB_RESULT": 9, "RISK_LAB_RULE": 3, "RISK_RULE_CLASS": 7,
    "CONSULTATION": 1, "UTTERANCE": 10,
}
PRIMARY_KEYS = {
    "DRUG": ("DRUG_ID",), "DRUG_LABEL_SECTION": ("SECTION_ID",), "PATIENT": ("PATIENT_ID",),
    "PATIENT_MEDICATION": ("PATIENT_MED_ID",), "LAB_RESULT": ("LAB_ID",), "RISK_LAB_RULE": ("RULE_ID",),
    "RISK_RULE_CLASS": ("RULE_ID", "CLASS_NAME"), "CONSULTATION": ("CONSULT_ID",),
    "UTTERANCE": ("UTTERANCE_ID",),
}
DRUG_IDS = {"ramipril": 101, "metoprolol succinate": 102,
            "furosemide": 103, "ibuprofen": 104}


@pytest.fixture(scope="module")
def schema():
    return parse_tables(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def columns(schema):
    return {table: [c.name for c in cols] for table, cols in schema.items()}


@pytest.fixture(scope="module")
def fx():
    return load_fixture(FIXTURE_PATH)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST_PATH)


@pytest.fixture(scope="module")
def labels(manifest):
    return [load_label(entry, LABEL_DIR) for entry in manifest]


@pytest.fixture(scope="module")
def rows(fx, labels, manifest, columns):
    return build_rows(fx, labels, manifest, columns)


def _label(labels, drug):
    return next(lb for lb in labels if lb.entry.generic_name == drug)


def _with_openfda(loaded, **openfda):
    """A copy of `loaded` whose `openfda` object is replaced (None values remove the key)."""
    merged = {**loaded.label.get("openfda", {}), **openfda}
    return replace(loaded, label={**loaded.label, "openfda": {k: v for k, v in merged.items() if v is not None}})


# --- Tables and columns (Requirements 3.3, design decision 5) ---


def test_every_seed_owned_table_is_built(rows):
    assert SEED_OWNED_TABLES == EXPECTED_TABLES
    assert tuple(rows) == EXPECTED_TABLES


def test_each_row_has_exactly_the_schema_file_columns_in_file_order(rows, columns):
    for table, built in rows.items():
        assert built, f"{table} has no rows"
        for row in built:
            assert list(row) == columns[table], table


def test_expected_row_counts(rows, labels):
    assert {table: len(built) for table, built in rows.items()
            if table != "DRUG_LABEL_SECTION"} == EXPECTED_COUNTS
    sections = rows["DRUG_LABEL_SECTION"]
    assert len([s for s in sections if s["DRUG_ID"] == 101]) == 4
    assert len(sections) == sum(len(import_sections(lb)[0]) for lb in labels)


def test_column_drift_is_rejected(fx, labels, manifest, columns):
    extra = {**columns, "DRUG": [*columns["DRUG"], "NEW_COLUMN"]}
    with pytest.raises(ValueError, match=r"DRUG.*NEW_COLUMN"):
        build_rows(fx, labels, manifest, extra)
    missing = {
        **columns, "UTTERANCE": [c for c in columns["UTTERANCE"] if c != "OFFSET_MS"]}
    with pytest.raises(ValueError, match=r"UTTERANCE.*OFFSET_MS"):
        build_rows(fx, labels, manifest, missing)
    no_table = {t: c for t, c in columns.items() if t != "RISK_RULE_CLASS"}
    with pytest.raises(ValueError, match="RISK_RULE_CLASS"):
        build_rows(fx, labels, manifest, no_table)


def test_built_strings_fit_their_declared_lengths(rows, schema):
    for table, built in rows.items():
        lengths = {}
        for col in schema[table]:
            match = re.fullmatch(r"(?:VAR)?CHAR\((\d+)\)", col.type_text)
            if match:
                lengths[col.name] = int(match.group(1))
        for row in built:
            for column, value in row.items():
                if isinstance(value, str):
                    assert len(
                        value) <= lengths[column], (table, column, len(value))


# --- Drugs and classes (Requirements 9.1, 9.3, 9.5, 9.6, 9.10) ---


def test_drug_rows(rows, labels, manifest):
    set_ids = {e.generic_name: e.set_id for e in manifest}
    drugs = rows["DRUG"]
    assert [(d["DRUG_ID"], d["GENERIC_NAME"], d["RXCUI"], d["IS_OTC"]) for d in drugs] == [
        (101, "ramipril", "35296", False),
        (102, "metoprolol succinate", "6918", False),
        (103, "furosemide", "4603", False),
        (104, "ibuprofen", "5640", True),
    ]
    for d in drugs:
        loaded = _label(labels, d["GENERIC_NAME"])
        brands = loaded.label.get("openfda", {}).get("brand_name") or []
        assert d["BRAND_NAMES"] == (", ".join(brands) or None)
        assert d["SOURCE_FETCHED_AT"] == loaded.metadata.fetched_at
        set_id = set_ids[d["GENERIC_NAME"]]
        assert d["SRC_NAME"] == f"openFDA label {set_id}; RxNorm {d['RXCUI']}"
        assert "openFDA" in d["SRC_NAME"] and set_id in d["SRC_NAME"] and "RxNorm" in d["SRC_NAME"]
    by_name = {d["GENERIC_NAME"]: d for d in drugs}
    assert by_name["ramipril"]["BRAND_NAMES"] == "Ramipril"
    assert by_name["furosemide"]["BRAND_NAMES"] == "Lasix"


def test_optional_drugs_get_no_rows(rows):
    """Design decision 7: spironolactone (105) and potassium chloride (106) are not in the manifest."""
    for table in ("DRUG", "DRUG_CLASS", "DRUG_LABEL_SECTION", "DRUG_APPEARANCE", "PATIENT_MEDICATION"):
        assert not {105, 106} & {r["DRUG_ID"] for r in rows[table]}, table


@pytest.mark.parametrize("brands, expected", [
    (["Zeta", "Alpha", "Mid"], "Zeta, Alpha, Mid"),
    ([], None),
    (None, None),
])
def test_brand_names_are_joined_in_snapshot_order_or_null(fx, labels, manifest, columns, brands, expected):
    changed = _with_openfda(labels[0], brand_name=brands)
    if brands is None:
        assert "brand_name" not in changed.label["openfda"]
    built = build_rows(fx, [changed, *labels[1:]], manifest, columns)
    assert built["DRUG"][0]["BRAND_NAMES"] == expected


def test_brand_names_null_without_an_openfda_object(fx, labels, manifest, columns):
    bare = replace(labels[0], label={
                   k: v for k, v in labels[0].label.items() if k != "openfda"})
    assert build_rows(fx, [bare, *labels[1:]], manifest,
                      columns)["DRUG"][0]["BRAND_NAMES"] is None


def test_drug_src_name_omits_rxnorm_without_rxcui(fx, labels, manifest, columns):
    drugs = (fx.drugs[0].model_copy(update={"rxcui": None}), *fx.drugs[1:])
    built = build_rows(fx.model_copy(
        update={"drugs": drugs}), labels, manifest, columns)
    row = built["DRUG"][0]
    assert row["RXCUI"] is None
    assert row["SRC_NAME"] == f"openFDA label {RAMIPRIL_SET_ID}"
    assert "RxNorm" not in row["SRC_NAME"]


def test_drug_class_rows(rows):
    assert [(c["DRUG_ID"], c["CLASS_NAME"], c["CLASS_TYPE"], c["SRC_NAME"]) for c in rows["DRUG_CLASS"]] == [
        (101, "ACE inhibitor", "EPC",
         "curated; openFDA EPC: Angiotensin Converting Enzyme Inhibitor [EPC]"),
        # the metoprolol succinate snapshot has no openfda.pharm_class_epc list
        (102, "beta blocker", "EPC", "curated"),
        (103, "loop diuretic", "EPC",
         "curated; openFDA EPC: Loop Diuretic [EPC]"),
        (104, "NSAID", "EPC",
         "curated; openFDA EPC: Nonsteroidal Anti-inflammatory Drug [EPC]"),
    ]


def test_metoprolol_snapshot_has_no_epc(labels):
    assert "pharm_class_epc" not in _label(
        labels, "metoprolol succinate").label.get("openfda", {})


@pytest.mark.parametrize("epc, expected", [
    (["First [EPC]", "Second [EPC]"], "curated; openFDA EPC: First [EPC]"),
    ([], "curated"),
    (None, "curated"),
])
def test_class_src_name_uses_the_first_epc_or_exactly_curated(fx, labels, manifest, columns, epc, expected):
    changed = _with_openfda(labels[0], pharm_class_epc=epc)
    built = build_rows(fx, [changed, *labels[1:]], manifest, columns)
    assert built["DRUG_CLASS"][0]["SRC_NAME"] == expected


def test_class_synonym_rows(rows):
    curator = "MedGuard team, demo-data-foundation"
    assert [tuple(r.values()) for r in rows["CLASS_SYNONYM"]] == [
        ("NSAID", "NSAIDs", curator),
        ("ACE inhibitor", "ACE inhibitors", curator),
        ("loop diuretic", "diuretic therapy", curator),
    ]


# --- Label sections (Requirement 8.6) ---


def test_label_section_rows_carry_provenance(rows, labels):
    by_drug_id = {DRUG_IDS[lb.entry.generic_name]: lb for lb in labels}
    sections = rows["DRUG_LABEL_SECTION"]
    ids = [s["SECTION_ID"] for s in sections]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for s in sections:
        loaded = by_drug_id[s["DRUG_ID"]]
        field, element = s["SECTION_TYPE"], s["SECTION_ID"] % 100
        assert s["SECTION_ID"] // 1000 == loaded.entry.position
        assert s["SECTION_TEXT"] == loaded.label[field][element]
        assert s["LABEL_SET_ID"] == loaded.label["set_id"] == loaded.entry.set_id
        assert s["LABEL_EFFECTIVE_AT"] == datetime.strptime(
            loaded.label["effective_time"], "%Y%m%d").date()
        assert s["SOURCE_URL"] == loaded.metadata.request_url
        assert s["SOURCE_FETCHED_AT"] == loaded.metadata.fetched_at
        assert s["CONTENT_SHA256"] == hashlib.sha256(
            s["SECTION_TEXT"].encode("utf-8")).hexdigest()
    ramipril = [s for s in sections if s["DRUG_ID"] == 101]
    assert [s["SECTION_ID"] for s in ramipril] == [1100, 1200, 1400, 1500]
    assert {(s["LABEL_SET_ID"], s["LABEL_EFFECTIVE_AT"])
            for s in ramipril} == {(RAMIPRIL_SET_ID, date(2022, 7, 1))}


# --- Risk rules (Requirements 10.4, 10.5, 10.8, 10.10) ---


def test_risk_rule_rows(rows, fx):
    rules = rows["RISK_LAB_RULE"]
    assert [(r["RULE_ID"], r["ANALYTE"], r["DIRECTION"], r["EVIDENCE_SECTION_ID"], r["CONCERN_AT"]) for r in rules] == [
        (401, "EGFR", "LOW", 1500, None),
        (402, "CREATININE", "HIGH", 1500, None),
        (403, "POTASSIUM", "HIGH", 1400, None),
    ]
    section_text = {s["SECTION_ID"]: s["SECTION_TEXT"]
                    for s in rows["DRUG_LABEL_SECTION"]}
    section_type = {s["SECTION_ID"]: s["SECTION_TYPE"]
                    for s in rows["DRUG_LABEL_SECTION"]}
    for rule, source in zip(rules, fx.risk_rules, strict=True):
        assert (rule["RULE_NAME"], rule["RATIONALE"], rule["EVIDENCE_QUOTE"]) == (
            source.rule_name, source.rationale, source.evidence_quote)
        assert verify_quote(rule["EVIDENCE_QUOTE"],
                            section_text[rule["EVIDENCE_SECTION_ID"]])
        assert RAMIPRIL_SET_ID in rule["SRC_NAME"]
        assert section_type[rule["EVIDENCE_SECTION_ID"]] in rule["SRC_NAME"]
    assert rules[0]["SRC_NAME"] == (
        f"Curated by MedGuard team from openFDA label {RAMIPRIL_SET_ID}, section drug_interactions[0]")
    assert rules[2]["SRC_NAME"] == (
        f"Curated by MedGuard team from openFDA label {RAMIPRIL_SET_ID}, section warnings_and_cautions[0]")


def test_risk_rule_class_rows(rows):
    triple = ["NSAID", "ACE inhibitor", "loop diuretic"]
    assert [(r["RULE_ID"], r["CLASS_NAME"]) for r in rows["RISK_RULE_CLASS"]] == [
        *((401, c) for c in triple), *((402, c) for c in triple), (403, "ACE inhibitor")]


def test_missing_evidence_section_is_rejected(fx, labels, manifest, columns):
    ramipril = labels[0]
    stripped = replace(ramipril, label={
                       k: v for k, v in ramipril.label.items() if k != "drug_interactions"})
    with pytest.raises(ValueError, match="drug_interactions"):
        build_rows(fx, [stripped, *labels[1:]], manifest, columns)


# --- Patient, consultation and script (Requirements 4.5, 3.3) ---


def test_patient_side_rows(rows, fx):
    assert rows["PATIENT"] == [{
        "PATIENT_ID": 1, "DISPLAY_NAME": "Patient A (72F)", "BIRTH_YEAR": 1954, "SEX": "F",
        "PRIMARY_DX": "Chronic heart failure (HFrEF)", "IS_SYNTHETIC": True}]
    assert [(m["PATIENT_MED_ID"], m["PATIENT_ID"], m["DRUG_ID"], m["STRENGTH"], m["SCHEDULE_TEXT"],
             m["STARTED_ON"], m["STOPPED_ON"]) for m in rows["PATIENT_MEDICATION"]] == [
        (201, 1, 101, "5 mg", "once in the morning", date(2024, 3, 4), None),
        (202, 1, 102, "47.5 mg", "with breakfast", date(2024, 3, 4), None),
        (203, 1, 103, "40 mg", "once in the morning", date(2025, 1, 20), None),
    ]
    assert [(a["DRUG_ID"], a["COLOR"], a["SHAPE"], a["IMPRINT"], a["STRENGTH"]) for a in rows["DRUG_APPEARANCE"]] == [
        (101, "white", "round", None, "5 mg"),
        (102, "yellow", "oval", None, "47.5 mg"),
        (103, "white", "oblong", None, "40 mg"),
    ]
    assert all("synthetic" in a["SRC_NAME"].lower()
               for a in rows["DRUG_APPEARANCE"])
    labs = rows["LAB_RESULT"]
    assert [lab["LAB_ID"] for lab in labs] == list(range(301, 310))
    assert {lab["PATIENT_ID"] for lab in labs} == {1}
    assert labs[3]["VALUE_NUM"] == Decimal(
        "0.97") and str(labs[5]["VALUE_NUM"]) == "1.20"
    assert labs[0]["REF_HIGH"] is None and labs[0]["MEASURED_AT"] == date(
        2026, 5, 14)


def test_consultation_and_utterance_rows(rows, fx):
    assert rows["CONSULTATION"] == [{
        "CONSULT_ID": 1, "PATIENT_ID": 1, "CLINICIAN": "Dr. Vogel",
        "STARTED_AT": datetime(2026, 11, 13, 9, 0, 0), "SCENARIO": "hf-follow-up-v1"}]
    utterances = rows["UTTERANCE"]
    assert [(u["UTTERANCE_ID"], u["SEQ"], u["SPEAKER"], u["OFFSET_MS"]) for u in utterances] == [
        (u.utterance_id, u.seq, u.speaker, u.offset_ms) for u in fx.utterances]
    assert [u["UTTERANCE_TEXT"]
            for u in utterances] == [u.text for u in fx.utterances]
    assert {u["CONSULT_ID"] for u in utterances} == {1}


# --- Determinism and traceable dates (Requirements 3.4, 3.5, 3.9, 17.5) ---


def _keys(built):
    return {table: [tuple(row[c] for c in PRIMARY_KEYS[table]) for row in built[table]] for table in PRIMARY_KEYS}


def test_two_builds_are_equal_with_the_same_primary_keys(rows, fx, labels, manifest, columns):
    again = build_rows(fx, labels, manifest, columns)
    assert again == rows
    reloaded_manifest = load_manifest(MANIFEST_PATH)
    fresh = build_rows(load_fixture(FIXTURE_PATH), [load_label(e, LABEL_DIR) for e in reloaded_manifest],
                       reloaded_manifest, columns)
    assert fresh == rows
    assert _keys(fresh) == _keys(rows)
    for table, keys in _keys(rows).items():
        assert len(set(keys)) == len(keys), f"duplicate primary key in {table}"


def test_every_date_and_timestamp_is_traceable(rows, fx, labels):
    allowed = {fx.as_of, fx.consultation.started_at}
    allowed |= {m.started_on for m in fx.medications} | {
        m.stopped_on for m in fx.medications if m.stopped_on}
    allowed |= {lab.measured_at for lab in fx.labs}
    allowed |= {lb.metadata.fetched_at for lb in labels}
    allowed |= {datetime.strptime(
        lb.label["effective_time"], "%Y%m%d").date() for lb in labels}
    seen = [value for built in rows.values() for row in built for value in row.values()
            if isinstance(value, date)]
    assert seen
    for value in seen:
        assert value in allowed, value
        if isinstance(value, datetime) and value.tzinfo is not None:
            assert value.utcoffset() == timedelta(0)


def test_build_rows_reads_no_clock_environment_or_random_source():
    source = Path(demo_fixture.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"os", "time", "random", "secrets",
                           "uuid", "socket", "urllib", "requests", "boto3"}
    assert not re.search(
        r"\.(now|today|utcnow)\(|getenv\(|environ\[|environ\.get", source)


# --- to_wire (design "Wire values for insert_multi", Requirement 3.9) ---


@pytest.mark.parametrize("value, wire", [
    (Decimal("0.97"), "0.97"),
    (Decimal("1.20"), "1.20"),
    (Decimal("60"), "60"),
    (Decimal("5.0"), "5.0"),
    (date(2026, 5, 14), "2026-05-14"),
    (datetime(2026, 11, 13, 9, 0, 0), "2026-11-13 09:00:00.000000"),
    (datetime(2026, 11, 13, 21, 4, 17, tzinfo=UTC), "2026-11-13 21:04:17.000000"),
    (datetime(2026, 11, 13, 21, 4, 17, tzinfo=timezone(
        timedelta(0))), "2026-11-13 21:04:17.000000"),
    (101, 101),
    ("once in the morning", "once in the morning"),
    (None, None),
])
def test_to_wire(value, wire):
    assert to_wire(value) == wire


@pytest.mark.parametrize("flag", [True, False])
def test_to_wire_keeps_booleans(flag):
    assert to_wire(flag) is flag


def test_to_wire_rejects_a_non_utc_zone_and_unknown_types():
    with pytest.raises(ValueError, match="UTC"):
        to_wire(datetime(2026, 11, 13, 22, 4, 17,
                tzinfo=timezone(timedelta(hours=1))))
    with pytest.raises(TypeError, match="float"):
        to_wire(0.97)


def test_every_built_value_converts(rows):
    for built in rows.values():
        for row in built:
            for value in row.values():
                assert type(to_wire(value)) in (int, bool, str, type(None))
    assert to_wire(rows["LAB_RESULT"][3]["VALUE_NUM"]) == "0.97"
    assert to_wire(rows["CONSULTATION"][0]["STARTED_AT"]
                   ) == "2026-11-13 09:00:00.000000"
