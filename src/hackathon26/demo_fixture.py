"""Demo_Fixture loader (no network, no database).

`data/demo/demo_fixture.json` holds every seed value that is not label text: the synthetic patient, her
medications, pill appearances, labs, the scripted consultation, drugs and classes, class synonyms and the
curated risk rules. `load_fixture` parses it into a strict, frozen `DemoFixture`:

- unknown keys and empty strings are rejected (Exasol stores an empty string as NULL, so use JSON null);
- dates are `YYYY-MM-DD` strings, the consultation start is `YYYY-MM-DDTHH:MM:SS` without a zone;
- decimals are JSON strings such as `"0.97"`, never JSON numbers, so no float rounding can happen.

Every problem is reported with its JSON path, e.g. `utterances[3].text`. There is a single patient and a
single consultation, so medications, labs and utterances carry no PATIENT_ID or CONSULT_ID of their own.
Medications, appearances and rule evidence name a drug by its generic name.

`fixture_problems` is the one validator for the cross-field invariants of Requirements 4, 5, 6, 8.11, 9
and 10. The seed refuses to connect while it returns anything, and the unit tests run it on the committed
fixture and on mutated copies. Quotes are checked only with `hackathon26.evidence.verify_quote`
(Requirement 11.7).

`build_rows` turns the fixture, the manifest and the loaded labels into the rows of every Seed_Owned_Table,
keyed by Schema_File column names, and `to_wire` converts each value to its `insert_multi` form. Both are
pure: they read no clock, environment or random source.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainValidator, ValidationError

from hackathon26.evidence import verify_quote
from hackathon26.labels import (
    DEMO_DRUGS,
    IMPORTED_FIELDS,
    OPTIONAL_DRUGS,
    LabelError,
    LoadedLabel,
    ManifestEntry,
    SectionRow,
    import_sections,
)
from hackathon26.schema_file import ColumnDef, parse_tables

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sql" / "01_schema.sql"

_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_TIMESTAMP_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\Z")
_DECIMAL_RE = re.compile(r"\A-?\d+(?:\.\d+)?\Z")


class FixtureError(Exception):
    """The Demo_Fixture could not be read or failed validation. `problems` holds (json_path, message)."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        super().__init__(
            "; ".join(f"{path}: {message}" for path, message in problems))
        self.problems = problems

    @property
    def paths(self) -> list[str]:
        return [path for path, _ in self.problems]


def _parse_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("must be a YYYY-MM-DD string")
    # also rejects impossible days such as 2026-02-30
    return date.fromisoformat(value)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_RE.match(value):
        raise ValueError(
            "must be a YYYY-MM-DDTHH:MM:SS string without a time zone")
    return datetime.fromisoformat(value)


def _parse_decimal(value: object) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL_RE.match(value):
        raise ValueError(
            'must be a decimal written as a JSON string, e.g. "0.97"')
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - the pattern already excludes this
        raise ValueError("not a decimal") from exc


IsoDate = Annotated[date, PlainValidator(_parse_date)]
NaiveTimestamp = Annotated[datetime, PlainValidator(_parse_timestamp)]
DecimalString = Annotated[Decimal, PlainValidator(_parse_decimal)]
Id = Annotated[int, Field(ge=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, str_min_length=1)


class Patient(_Strict):
    patient_id: Id
    display_name: str
    birth_year: int
    sex: str
    primary_dx: str
    is_synthetic: bool


class DrugClass(_Strict):
    class_name: str
    class_type: Literal["EPC", "MOA", "CYP", "ATC"]


class Drug(_Strict):
    drug_id: Id
    generic_name: str
    rxcui: str | None  # RxNorm ingredient concept id, null if unmapped
    is_otc: bool
    classes: tuple[DrugClass, ...]


class Medication(_Strict):
    patient_med_id: Id
    drug: str  # generic name
    strength: str
    schedule_text: str
    started_on: IsoDate
    stopped_on: IsoDate | None


class Appearance(_Strict):
    drug: str  # generic name
    color: str
    shape: str
    imprint: str | None
    strength: str
    manufacturer: str  # fictional
    src_name: str


class Lab(_Strict):
    lab_id: Id
    analyte: str
    value_num: DecimalString | None
    unit: str | None
    ref_low: DecimalString | None
    ref_high: DecimalString | None
    measured_at: IsoDate


class Consultation(_Strict):
    consult_id: Id
    clinician: str
    started_at: NaiveTimestamp
    scenario: str


class Utterance(_Strict):
    utterance_id: Id
    seq: int
    speaker: Literal["DOCTOR", "PATIENT"]
    offset_ms: int
    text: str


class ClassSynonym(_Strict):
    class_name: str
    synonym: str
    curated_by: str


class EvidencePointer(_Strict):
    """Names a DRUG_LABEL_SECTION by (drug, field, element); the SECTION_ID is computed at build time."""

    drug: str  # generic name
    field: Literal[IMPORTED_FIELDS]  # type: ignore[valid-type]
    element: Annotated[int, Field(ge=0, le=99)]


class RiskRule(_Strict):
    rule_id: Id
    rule_name: str
    analyte: str
    direction: Literal["LOW", "HIGH"]
    concern_at: DecimalString | None
    required_classes: tuple[str, ...]
    evidence: EvidencePointer
    evidence_quote: str
    rationale: str


class DemoFixture(_Strict):
    as_of: IsoDate
    patient: Patient
    drugs: tuple[Drug, ...]
    medications: tuple[Medication, ...]
    appearances: tuple[Appearance, ...]
    labs: tuple[Lab, ...]
    consultation: Consultation
    utterances: tuple[Utterance, ...]
    class_synonyms: tuple[ClassSynonym, ...]
    risk_rules: tuple[RiskRule, ...]


def _json_path(loc: tuple) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "(root)"


def load_fixture(path: Path) -> DemoFixture:
    """Read and validate the Demo_Fixture. Raises `FixtureError` naming the JSON path of each problem."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise FixtureError(
            [("(file)", f"cannot read {path}: {exc.strerror or exc}")]) from exc
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise FixtureError(
            [("(file)", f"{path} is not valid JSON: {exc}")]) from exc
    try:
        # JSON mode: strict typing still accepts JSON arrays for the tuple fields.
        return DemoFixture.model_validate_json(text)
    except ValidationError as exc:
        problems = [(_json_path(err["loc"]), err["msg"])
                    for err in exc.errors(include_url=False)]
        raise FixtureError(problems) from exc


# --- Validator -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """One fixture or input fault: the JSON path at fault, the requirement it breaks, and why."""

    field: str
    requirement: str
    message: str


# Requirement 4.6: the colour each current medication must have.
_EXPECTED_COLOURS = {"ramipril": "white",
                     "furosemide": "white", "metoprolol succinate": "yellow"}
_SAME_SCHEDULE_AND_DIFFERENT_SHAPE = ("ramipril", "furosemide")  # 4.6, 4.7
# Requirement 5.6: the trend direction of each analyte in MEASURED_AT order.
_TRENDS = {"EGFR": "falling", "POTASSIUM": "rising", "CREATININE": "rising"}
_LAB_WINDOW_DAYS = 365  # Requirement 5.5: fewer than 365 days before As_Of_Date
# Requirements 6.3, 6.4, 6.9: (SEQ, exact case-sensitive phrase, requirement)
_REQUIRED_PHRASES = (
    (1, "Good morning", "6.9"),
    (2, "the white one", "6.3"),
    (2, "the small yellow one", "6.3"),
    (3, "water tablet", "6.9"),
    (4, "the long white one", "6.3"),
    (4, "dizzy", "6.9"),
    (6, "something for my knee", "6.4"),
    (9, "bring the box", "6.9"),
)
_SCRIPT_LENGTH = 10  # Requirements 6.2, 6.6
_IBUPROFEN_SEQ = 8  # Requirement 6.5
_NAMED_DRUG_WORDS = ("ramipril", "metoprolol", "furosemide")  # Requirement 6.5
_DOSE_PHRASES = ("mg", "milligram", "milligrams", "once a day",
                 "twice a day", "times a day")  # 6.11
_MIN_OFFSET_STEP_MS = 2000  # Requirement 6.7
_MAX_LAST_OFFSET_MS = 90000
_MAX_UTTERANCE_CHARS = 4000  # Requirement 6.10


def _whole(phrase: str) -> re.Pattern[str]:
    """Case-insensitive phrase with no letter or digit directly before or after it."""
    return re.compile(r"(?<![^\W_])" + re.escape(phrase) + r"(?![^\W_])", re.IGNORECASE)


_IBUPROFEN_RE = _whole("ibuprofen")
_DOSE_RES = tuple((phrase, _whole(phrase)) for phrase in _DOSE_PHRASES)


@lru_cache(maxsize=1)
def _repo_schema() -> dict[str, list[ColumnDef]]:
    return parse_tables(SCHEMA_FILE.read_text(encoding="utf-8"))


def _declared_length(schema: dict[str, list[ColumnDef]], table: str, column: str) -> int | None:
    for col in schema.get(table, ()):
        if col.name == column:
            match = re.fullmatch(
                r"(?:VAR)?CHAR\((\d+)\)", col.type_text, re.IGNORECASE)
            return int(match.group(1)) if match else None
    return None


def _is_current(med: Medication, as_of: date) -> bool:
    """Current at As_Of_Date: started on or before it and not stopped on or before it."""
    return (med.started_on is not None and med.started_on <= as_of
            and (med.stopped_on is None or med.stopped_on > as_of))


def _flagged(lab: Lab) -> bool:
    """Reference_Range_Flag: VALUE_NUM below REF_LOW or above REF_HIGH."""
    return ((lab.ref_low is not None and lab.value_num < lab.ref_low)
            or (lab.ref_high is not None and lab.value_num > lab.ref_high))


def _fixture_strings(fx: DemoFixture) -> Iterator[tuple[str, str | None, str, str]]:
    """(json_path, value, table, column) for every fixture string stored in a VARCHAR column."""
    p = fx.patient
    for key in ("display_name", "sex", "primary_dx"):
        yield f"patient.{key}", getattr(p, key), "PATIENT", key.upper()
    for i, d in enumerate(fx.drugs):
        yield f"drugs[{i}].generic_name", d.generic_name, "DRUG", "GENERIC_NAME"
        yield f"drugs[{i}].rxcui", d.rxcui, "DRUG", "RXCUI"
        for j, c in enumerate(d.classes):
            yield f"drugs[{i}].classes[{j}].class_name", c.class_name, "DRUG_CLASS", "CLASS_NAME"
            yield f"drugs[{i}].classes[{j}].class_type", c.class_type, "DRUG_CLASS", "CLASS_TYPE"
    for i, m in enumerate(fx.medications):
        for key in ("strength", "schedule_text"):
            yield f"medications[{i}].{key}", getattr(m, key), "PATIENT_MEDICATION", key.upper()
    for i, a in enumerate(fx.appearances):
        for key in ("color", "shape", "imprint", "strength", "manufacturer", "src_name"):
            yield f"appearances[{i}].{key}", getattr(a, key), "DRUG_APPEARANCE", key.upper()
    for i, lab in enumerate(fx.labs):
        for key in ("analyte", "unit"):
            yield f"labs[{i}].{key}", getattr(lab, key), "LAB_RESULT", key.upper()
    for key in ("clinician", "scenario"):
        yield f"consultation.{key}", getattr(fx.consultation, key), "CONSULTATION", key.upper()
    for i, u in enumerate(fx.utterances):
        yield f"utterances[{i}].speaker", u.speaker, "UTTERANCE", "SPEAKER"
        yield f"utterances[{i}].text", u.text, "UTTERANCE", "UTTERANCE_TEXT"
    for i, s in enumerate(fx.class_synonyms):
        for key in ("class_name", "synonym", "curated_by"):
            yield f"class_synonyms[{i}].{key}", getattr(s, key), "CLASS_SYNONYM", key.upper()
    for i, r in enumerate(fx.risk_rules):
        for key in ("rule_name", "analyte", "direction", "rationale", "evidence_quote"):
            yield f"risk_rules[{i}].{key}", getattr(r, key), "RISK_LAB_RULE", key.upper()
        for k, c in enumerate(r.required_classes):
            yield f"risk_rules[{i}].required_classes[{k}]", c, "RISK_RULE_CLASS", "CLASS_NAME"


def curated_text(fx: DemoFixture) -> Iterator[tuple[str, str, bool]]:
    """(json_path, value, is_utterance) for every Curated_Text value of the Demo_Fixture (Requirement 14).

    Curated_Text is the free text the team authors: utterances, the patient display name, the clinician
    label, the scenario name, the invented appearance text (colour, shape, manufacturer, SRC_NAME), class
    synonyms with their CURATED_BY, rule names and rationales. It excludes openFDA label text, evidence
    quotes and the record fields PRIMARY_DX, STRENGTH and SCHEDULE_TEXT, and also the controlled codes
    (sex, speaker, analyte, direction, class type, RxCUI) and drug and class names. `is_utterance` is true
    only for UTTERANCE_TEXT, which may quote a patient's own words.
    """
    yield "patient.display_name", fx.patient.display_name, False
    yield "consultation.clinician", fx.consultation.clinician, False
    yield "consultation.scenario", fx.consultation.scenario, False
    for i, u in enumerate(fx.utterances):
        yield f"utterances[{i}].text", u.text, True
    for i, a in enumerate(fx.appearances):
        for key in ("color", "shape", "manufacturer", "src_name"):
            yield f"appearances[{i}].{key}", getattr(a, key), False
    for i, s in enumerate(fx.class_synonyms):
        for key in ("synonym", "curated_by"):
            yield f"class_synonyms[{i}].{key}", getattr(s, key), False
    for i, r in enumerate(fx.risk_rules):
        for key in ("rule_name", "rationale"):
            yield f"risk_rules[{i}].{key}", getattr(r, key), False


def _index_sections(rows: list[SectionRow]) -> dict[tuple[str, str, int], SectionRow]:
    return {(row.generic_name, row.section_type, row.element): row for row in rows}


def _manifest_labels(labels: list[LoadedLabel], manifest: list[ManifestEntry]) -> list[LoadedLabel]:
    """The labels whose entry is in the manifest (Requirement 8.1: other files are ignored)."""
    entries = set(manifest)
    return [loaded for loaded in labels if loaded.entry in entries]


def evidence_sections(
    labels: list[LoadedLabel], manifest: list[ManifestEntry]
) -> dict[tuple[str, str, int], SectionRow]:
    """Every imported DRUG_LABEL_SECTION row of the manifest's labels, keyed by (drug, field, element).

    Raises LabelError from `import_sections` for a label that cannot be imported.
    """
    rows: list[SectionRow] = []
    for loaded in _manifest_labels(labels, manifest):
        rows.extend(import_sections(loaded)[0])
    return _index_sections(rows)


def fixture_problems(
    fx: DemoFixture,
    labels: list[LoadedLabel],
    manifest: list[ManifestEntry],
    *,
    schema: dict[str, list[ColumnDef]] | None = None,
) -> list[Problem]:
    """Check every cross-field Demo_Fixture invariant against the loaded labels and the manifest.

    Returns one `Problem` per fault, each with the JSON path at fault and the requirement number; an empty
    list means the seed may connect. `schema` is the parsed Schema_File (default: `sql/01_schema.sql`),
    used for the column-length checks of Requirement 8.11. Pure apart from reading that default file.
    """
    problems: list[Problem] = []

    def add(field: str, requirement: str, message: str) -> None:
        problems.append(Problem(field, requirement, message))

    manifest_labels = _manifest_labels(labels, manifest)
    sections = _check_labels(manifest_labels, manifest, add)
    seeded = _check_drugs(fx, manifest, add)
    _check_medications_and_appearances(fx, seeded, manifest_labels, add)
    _check_labs(fx, add)
    _check_script(fx, add)
    _check_rules(fx, seeded, manifest, sections, add)
    _check_lengths(fx, manifest_labels, sections,
                   schema if schema is not None else _repo_schema(), add)
    return problems


def _check_labels(manifest_labels, manifest, add) -> dict[tuple[str, str, int], SectionRow]:
    loaded_entries = {loaded.entry for loaded in manifest_labels}
    for entry in manifest:
        if entry not in loaded_entries:
            add(f"labels[{entry.generic_name}]", "8.2",
                f"{entry.generic_name}: no Label_Snapshot was loaded for this Label_Manifest entry")
    rows: list[SectionRow] = []
    for loaded in manifest_labels:
        try:
            rows.extend(import_sections(loaded)[0])
        except LabelError as exc:
            add(f"labels[{loaded.entry.generic_name}]", "8.3", str(exc))
    return _index_sections(rows)


def _check_drugs(fx: DemoFixture, manifest: list[ManifestEntry], add) -> dict[str, Drug]:
    """Requirements 9.1 and 9.11. Returns the fixture drugs that get a DRUG row in this run, by name."""
    in_manifest = {entry.generic_name for entry in manifest}
    fixture_names: set[str] = set()
    seeded: dict[str, Drug] = {}
    for i, drug in enumerate(fx.drugs):
        name, path = drug.generic_name, f"drugs[{i}].generic_name"
        if name in fixture_names:
            add(path, "9.1", f"drug {name!r} is listed more than once")
            continue
        fixture_names.add(name)
        if name in in_manifest:
            seeded[name] = drug
        elif name in DEMO_DRUGS:
            add(path, "9.11",
                f"Demo_Drug {name!r} has no Label_Manifest entry")
        elif name not in OPTIONAL_DRUGS:
            add(path, "9.1",
                f"drug {name!r} is neither an Optional_Drug nor in the Label_Manifest")
    for drug in DEMO_DRUGS:
        if drug not in fixture_names:
            add("drugs", "9.1",
                f"Demo_Drug {drug!r} has no fixture drug entry")
    for entry in manifest:
        if entry.generic_name not in fixture_names:
            add(f"label_manifest.labels[{entry.position - 1}].generic_name", "9.1",
                f"Label_Manifest drug {entry.generic_name!r} has no fixture drug entry")
    return seeded


def _check_medications_and_appearances(fx: DemoFixture, seeded: dict[str, Drug], manifest_labels, add) -> None:
    # Requirement 4.10: every medication and appearance names a seeded drug
    for i, med in enumerate(fx.medications):
        if med.drug not in seeded:
            add(f"medications[{i}].drug", "4.10",
                f"medication names drug {med.drug!r}, which has no DRUG row in this run")
    for i, app in enumerate(fx.appearances):
        if app.drug not in seeded:
            add(f"appearances[{i}].drug", "4.10",
                f"appearance names drug {app.drug!r}, which has no DRUG row in this run")

    current: dict[str, tuple[int, Medication]] = {}
    for i, med in enumerate(fx.medications):
        if _is_current(med, fx.as_of):
            current.setdefault(med.drug, (i, med))

    # Requirements 4.5, 4.8: one appearance per current medication, synthetic, no imprint, same strength
    appearance_of: dict[str, tuple[int, Appearance]] = {}
    for i, app in enumerate(fx.appearances):
        if app.drug not in current:
            add(f"appearances[{i}].drug", "4.5",
                f"appearance for {app.drug!r}, which is not a current medication at {fx.as_of}")
        elif app.drug in appearance_of:
            add(f"appearances[{i}].drug", "4.5",
                f"second appearance for {app.drug!r}")
            continue
        else:
            _, med = current[app.drug]
            if app.strength != med.strength:
                add(f"appearances[{i}].strength", "4.5",
                    f"{app.drug}: appearance strength {app.strength!r} differs from medication strength "
                    f"{med.strength!r}")
        appearance_of.setdefault(app.drug, (i, app))
        if app.imprint is not None:
            add(f"appearances[{i}].imprint", "4.5",
                f"{app.drug}: IMPRINT must be null")
        if "synthetic" not in (app.src_name or "").casefold():
            add(f"appearances[{i}].src_name", "4.8",
                f"{app.drug}: SRC_NAME must contain 'synthetic'")
    for drug in current:
        if drug not in appearance_of:
            add("appearances", "4.5",
                f"current medication {drug!r} has no appearance")

    # Requirement 4.6: two white (ramipril, furosemide), one yellow (metoprolol succinate)
    for drug, colour in _EXPECTED_COLOURS.items():
        if drug not in current:
            add("medications", "4.6",
                f"{drug!r} must be a current medication with a {colour} appearance")
    for drug, (i, app) in appearance_of.items():
        if drug not in current:
            continue
        expected = _EXPECTED_COLOURS.get(drug)
        if expected is not None and app.color != expected:
            add(f"appearances[{i}].color", "4.6",
                f"{drug} must be {expected!r}, found {app.color!r}")
        elif expected is None and app.color in set(_EXPECTED_COLOURS.values()):
            add(f"appearances[{i}].color", "4.6",
                f"{drug} must not be {app.color!r}: exactly two current medications are white and one yellow")

    a, b = _SAME_SCHEDULE_AND_DIFFERENT_SHAPE
    if a in current and b in current:
        (ia, med_a), (ib, med_b) = current[a], current[b]
        if med_a.schedule_text != med_b.schedule_text:
            for i, med, other in ((ia, med_a, med_b), (ib, med_b, med_a)):
                add(f"medications[{i}].schedule_text", "4.6",
                    f"{med.drug} schedule {med.schedule_text!r} differs from {other.drug} "
                    f"schedule {other.schedule_text!r}")
    # Requirement 4.7: ramipril and furosemide have different, non-null shapes
    pair = [appearance_of[d] for d in (a, b) if d in appearance_of]
    for i, app in pair:
        if not app.shape:
            add(f"appearances[{i}].shape", "4.7",
                f"{app.drug}: SHAPE must be non-null")
    if len(pair) == 2 and pair[0][1].shape and pair[1][1].shape:
        (ia, app_a), (ib, app_b) = pair
        if app_a.shape.strip().casefold() == app_b.shape.strip().casefold():
            for i, app in ((ia, app_a), (ib, app_b)):
                add(f"appearances[{i}].shape", "4.7",
                    f"{a} and {b} share SHAPE {app.shape!r}, so colour plus shape cannot separate them")

    # Requirement 4.9: fictional manufacturers only
    real: dict[str, str] = {}
    for loaded in manifest_labels:
        openfda = loaded.label.get("openfda")
        names = openfda.get("manufacturer_name") if isinstance(
            openfda, dict) else None
        for name in names if isinstance(names, list) else ():
            if isinstance(name, str):
                real.setdefault(name.casefold(), name)
    for i, app in enumerate(fx.appearances):
        match = real.get((app.manufacturer or "").casefold())
        if match is not None:
            add(f"appearances[{i}].manufacturer", "4.9",
                f"{app.drug}: MANUFACTURER {app.manufacturer!r} equals the snapshot manufacturer {match!r}")


def _check_labs(fx: DemoFixture, add) -> None:
    by_analyte: dict[str, list[int]] = {}
    for i, lab in enumerate(fx.labs):
        p = f"labs[{i}]"
        # Requirement 5.4: completeness and a well-formed range
        if lab.value_num is None:
            add(f"{p}.value_num", "5.4", f"{lab.analyte}: VALUE_NUM is null")
        if lab.unit is None:
            add(f"{p}.unit", "5.4", f"{lab.analyte}: UNIT is null")
        if lab.measured_at is None:
            add(f"{p}.measured_at", "5.4",
                f"{lab.analyte}: MEASURED_AT is null")
        if lab.ref_low is None and lab.ref_high is None:
            for key in ("ref_low", "ref_high"):
                add(f"{p}.{key}", "5.4",
                    f"{lab.analyte}: REF_LOW and REF_HIGH are both null")
        elif lab.ref_low is not None and lab.ref_high is not None and lab.ref_low >= lab.ref_high:
            for key in ("ref_low", "ref_high"):
                add(f"{p}.{key}", "5.4",
                    f"{lab.analyte}: REF_LOW {lab.ref_low} is not below REF_HIGH {lab.ref_high}")
        # Requirement 5.5: on or before As_Of_Date and fewer than 365 days before it
        if lab.measured_at is not None:
            age = (fx.as_of - lab.measured_at).days
            if age < 0 or age >= _LAB_WINDOW_DAYS:
                add(f"{p}.measured_at", "5.5",
                    f"{lab.analyte} measured {lab.measured_at} is outside the {_LAB_WINDOW_DAYS}-day window "
                    f"ending {fx.as_of}")
            by_analyte.setdefault(lab.analyte, []).append(i)

    for analyte, indexes in by_analyte.items():
        # Requirement 5.6: distinct dates
        dates: dict[date, list[int]] = {}
        for i in indexes:
            dates.setdefault(fx.labs[i].measured_at, []).append(i)
        for day, same in dates.items():
            if len(same) > 1:
                for i in same:
                    add(f"labs[{i}].measured_at", "5.6",
                        f"{analyte} has {len(same)} results on {day}")
        ordered = sorted(indexes, key=lambda i: (fx.labs[i].measured_at, i))
        valued = [i for i in ordered if fx.labs[i].value_num is not None]
        # Requirement 5.6: trend direction
        trend = _TRENDS.get(analyte)
        for prev, cur in zip(valued, valued[1:]):
            v0, v1 = fx.labs[prev].value_num, fx.labs[cur].value_num
            if (trend == "falling" and not v1 < v0) or (trend == "rising" and not v1 > v0):
                for i in (prev, cur):
                    add(f"labs[{i}].value_num", "5.6",
                        f"{analyte} must be {trend} in date order, but goes {v0} -> {v1}")
        # Requirement 5.8: earliest inside its range, latest outside
        if valued:
            first, last = valued[0], valued[-1]
            if _flagged(fx.labs[first]):
                add(f"labs[{first}].value_num", "5.8",
                    f"earliest {analyte} value {fx.labs[first].value_num} must be inside its reference range")
            if not _flagged(fx.labs[last]):
                add(f"labs[{last}].value_num", "5.8",
                    f"latest {analyte} value {fx.labs[last].value_num} must be outside its reference range")


def _check_script(fx: DemoFixture, add) -> None:
    utterances = fx.utterances
    if len(utterances) != _SCRIPT_LENGTH:
        add("utterances", "6.2",
            f"the Demo_Script has {len(utterances)} utterances, expected {_SCRIPT_LENGTH}")

    # Requirement 6.6: SEQ values 1..10, each exactly once
    seq_count: dict[int, int] = {}
    for u in utterances:
        seq_count[u.seq] = seq_count.get(u.seq, 0) + 1
    for i, u in enumerate(utterances):
        if not 1 <= u.seq <= _SCRIPT_LENGTH:
            add(f"utterances[{i}].seq", "6.6",
                f"SEQ {u.seq} is outside 1..{_SCRIPT_LENGTH}")
        elif seq_count[u.seq] > 1:
            add(f"utterances[{i}].seq", "6.6",
                f"SEQ {u.seq} is used {seq_count[u.seq]} times")
    for seq in range(1, _SCRIPT_LENGTH + 1):
        if seq not in seq_count:
            add("utterances", "6.6", f"SEQ {seq} is missing")

    by_seq: dict[int, int] = {}
    for i, u in enumerate(utterances):
        by_seq.setdefault(u.seq, i)
    named = sorted(set(_NAMED_DRUG_WORDS) | {
        d.generic_name.casefold() for d in fx.drugs if d.generic_name != "ibuprofen"})

    for i, u in enumerate(utterances):
        p = f"utterances[{i}]"
        # Requirement 6.2: odd SEQ DOCTOR, even SEQ PATIENT
        expected = "DOCTOR" if u.seq % 2 else "PATIENT"
        if u.speaker != expected:
            add(f"{p}.speaker", "6.2",
                f"SEQ {u.seq} must be spoken by {expected}, found {u.speaker}")
        text = u.text if isinstance(u.text, str) else ""
        # Requirement 6.10: 1 to 4000 characters with a non-whitespace character
        if not 1 <= len(text) <= _MAX_UTTERANCE_CHARS or not text.strip():
            add(f"{p}.text", "6.10",
                f"SEQ {u.seq}: text must be 1 to {_MAX_UTTERANCE_CHARS} characters with a non-whitespace "
                f"character (found {len(text)} characters)")
        # Requirement 6.5: ibuprofen only in SEQ 8, no other drug name anywhere
        has_ibuprofen = _IBUPROFEN_RE.search(text) is not None
        if u.seq == _IBUPROFEN_SEQ and not has_ibuprofen:
            add(f"{p}.text", "6.5", f"SEQ {u.seq} must name 'ibuprofen'")
        elif u.seq != _IBUPROFEN_SEQ and has_ibuprofen:
            add(f"{p}.text", "6.5",
                f"SEQ {u.seq} names 'ibuprofen', which belongs only in SEQ {_IBUPROFEN_SEQ}")
        folded = text.casefold()
        for name in named:
            if name in folded:
                add(f"{p}.text", "6.5", f"SEQ {u.seq} names the drug {name!r}")
        # Requirement 6.11: no digit and no dose wording
        if any(ch.isdigit() for ch in text):
            add(f"{p}.text", "6.11", f"SEQ {u.seq} contains a digit")
        for phrase, pattern in _DOSE_RES:
            if pattern.search(text):
                add(f"{p}.text", "6.11", f"SEQ {u.seq} contains {phrase!r}")

    # Requirements 6.3, 6.4, 6.9: exact phrases at their SEQ
    for seq, phrase, requirement in _REQUIRED_PHRASES:
        i = by_seq.get(seq)
        if i is None:
            add("utterances", requirement,
                f"no utterance with SEQ {seq} to hold {phrase!r}")
        elif phrase not in utterances[i].text:
            add(f"utterances[{i}].text", requirement,
                f"SEQ {seq} must contain {phrase!r} (case-sensitive)")

    # Requirement 6.7: OFFSET_MS 0 at SEQ 1, steps of at least 2000, at most 90000 at SEQ 10
    for i, u in enumerate(utterances):
        if not isinstance(u.offset_ms, int) or isinstance(u.offset_ms, bool):
            add(f"utterances[{i}].offset_ms", "6.7",
                f"SEQ {u.seq}: OFFSET_MS must be an integer")
    if any(not isinstance(u.offset_ms, int) or isinstance(u.offset_ms, bool) for u in utterances):
        return
    order = sorted(range(len(utterances)),
                   key=lambda i: (utterances[i].seq, i))
    for i in order:
        u = utterances[i]
        if u.seq == 1 and u.offset_ms != 0:
            add(f"utterances[{i}].offset_ms", "6.7",
                f"SEQ 1 must have OFFSET_MS 0, found {u.offset_ms}")
        if u.seq == _SCRIPT_LENGTH and u.offset_ms > _MAX_LAST_OFFSET_MS:
            add(f"utterances[{i}].offset_ms", "6.7",
                f"SEQ {u.seq} OFFSET_MS {u.offset_ms} is above {_MAX_LAST_OFFSET_MS}")
    for prev, cur in zip(order, order[1:]):
        step = utterances[cur].offset_ms - utterances[prev].offset_ms
        if step < _MIN_OFFSET_STEP_MS:
            for i in (prev, cur):
                add(f"utterances[{i}].offset_ms", "6.7",
                    f"OFFSET_MS step from SEQ {utterances[prev].seq} to SEQ {utterances[cur].seq} is {step} ms, "
                    f"below {_MIN_OFFSET_STEP_MS}")


def _check_rules(fx: DemoFixture, seeded: dict[str, Drug], manifest, sections, add) -> None:
    seeded_classes = {c.class_name for d in seeded.values() for c in d.classes}
    synonyms: dict[str, list[str]] = {}
    for s in fx.class_synonyms:
        synonyms.setdefault(s.class_name, []).append(s.synonym)
    set_ids = {entry.generic_name: entry.set_id for entry in manifest}
    owner_classes = {d.generic_name: {
        c.class_name for c in d.classes} for d in fx.drugs}

    for r, rule in enumerate(fx.risk_rules):
        p = f"risk_rules[{r}]"
        ev = rule.evidence
        quote = rule.evidence_quote or ""
        seen: set[str] = set()
        for k, class_name in enumerate(rule.required_classes):
            path = f"{p}.required_classes[{k}]"
            if class_name in seen:
                add(path, "1.2",
                    f"{rule.rule_name}: class {class_name!r} is listed twice")
            seen.add(class_name)
            # Requirement 9.9: exact, case-sensitive match with a seeded CLASS_NAME
            if class_name not in seeded_classes:
                add(path, "9.9",
                    f"{rule.rule_name}: required class {class_name!r} equals no seeded CLASS_NAME exactly")
            # Requirement 9.8: grounded in the quote (name or synonym) or owned by the section's drug
            words = [class_name, *synonyms.get(class_name, [])]
            in_quote = any(w.casefold() in quote.casefold() for w in words)
            owned = class_name in owner_classes.get(ev.drug, set())
            if not (in_quote or owned):
                add(path, "9.8",
                    f"{rule.rule_name}: required class {class_name!r} is neither named in the quote nor a class "
                    f"of {ev.drug!r}, which owns the evidence section")

        # Requirement 10.6: the section exists and the quote is verbatim in it
        set_id = set_ids.get(ev.drug, "(no Label_Manifest entry)")
        where = f"{rule.rule_name} (LABEL_SET_ID {set_id}, SECTION_TYPE {ev.field})"
        section = sections.get((ev.drug, ev.field, ev.element))
        if section is None:
            add(f"{p}.evidence", "10.6",
                f"{where}: no imported section {ev.drug} {ev.field}[{ev.element}]")
        elif not verify_quote(rule.evidence_quote, section.text):
            add(f"{p}.evidence_quote", "10.6",
                f"{where}: the quote is not a contiguous, case-sensitive substring of section "
                f"{section.section_id}")


def _check_lengths(fx: DemoFixture, manifest_labels, sections, schema, add) -> None:
    """Requirement 8.11: every value fits the declared length of its Schema_File column."""

    def check(path: str, value: object, table: str, column: str, who: str) -> None:
        if value is None:
            return
        limit = _declared_length(schema, table, column)
        if limit is None:
            add(path, "8.11",
                f"{who}: {table}.{column} has no declared character length in the Schema_File")
        elif isinstance(value, str) and len(value) > limit:
            add(path, "8.11",
                f"{who}: {table}.{column} value has {len(value)} characters, above the declared {limit}")

    for path, value, table, column in _fixture_strings(fx):
        check(path, value, table, column, path)
    for loaded in manifest_labels:
        drug = loaded.entry.generic_name
        check(f"labels[{drug}].set_id", loaded.label.get("set_id"),
              "DRUG_LABEL_SECTION", "LABEL_SET_ID", drug)
        check(f"labels[{drug}].metadata.request_url", loaded.metadata.request_url,
              "DRUG_LABEL_SECTION", "SOURCE_URL", drug)
    for (drug, field, element), row in sections.items():
        check(f"labels[{drug}].{field}[{element}]", row.section_type,
              "DRUG_LABEL_SECTION", "SECTION_TYPE", drug)
        check(f"labels[{drug}].{field}[{element}]", row.text,
              "DRUG_LABEL_SECTION", "SECTION_TEXT", drug)

    # Values that build_rows assembles from the snapshots and the fixture
    fixture_drugs = {d.generic_name: (i, d) for i, d in enumerate(fx.drugs)}
    set_ids: dict[str, str] = {}
    for loaded in manifest_labels:
        drug = loaded.entry.generic_name
        set_ids[drug] = loaded.entry.set_id
        path = f"labels[{drug}].openfda.brand_name"
        try:
            check(path, _brand_names(loaded), "DRUG", "BRAND_NAMES", drug)
        except LabelError as exc:
            add(path, "9.10", str(exc))
        if drug not in fixture_drugs:
            continue
        i, fixture_drug = fixture_drugs[drug]
        check(f"drugs[{i}].rxcui", _drug_src_name(loaded.entry.set_id, fixture_drug.rxcui),
              "DRUG", "SRC_NAME", drug)
        path = f"labels[{drug}].openfda.pharm_class_epc[0]"
        try:
            class_src = _class_src_name(loaded)
        except LabelError as exc:
            add(path, "9.5", str(exc))
            continue
        if fixture_drug.classes:
            check(path, class_src, "DRUG_CLASS", "SRC_NAME",
                  f"{drug} (DRUG_ID {fixture_drug.drug_id})")
    for r, rule in enumerate(fx.risk_rules):
        if rule.evidence.drug in set_ids:
            check(f"risk_rules[{r}].evidence", _rule_src_name(set_ids[rule.evidence.drug], rule.evidence),
                  "RISK_LAB_RULE", "SRC_NAME", rule.rule_name)


# --- Row building ----------------------------------------------------------------------------------

# Schema_File order. These are the only tables a Default_Seed_Run writes (Requirement 3.3, 3.6).
SEED_OWNED_TABLES = (
    "DRUG", "DRUG_CLASS", "CLASS_SYNONYM", "DRUG_LABEL_SECTION", "DRUG_APPEARANCE", "PATIENT",
    "PATIENT_MEDICATION", "LAB_RESULT", "RISK_LAB_RULE", "RISK_RULE_CLASS", "CONSULTATION", "UTTERANCE",
)

Value = int | str | bool | Decimal | date | datetime | None
SeedRows = dict[str, list[dict[str, Value]]]


def _openfda_strings(loaded: LoadedLabel, key: str) -> list[str] | None:
    """The `openfda.<key>` list of a label, or None when `openfda` or the key is absent."""
    drug = loaded.entry.generic_name
    openfda = loaded.label.get("openfda")
    if openfda is None:
        return None
    if not isinstance(openfda, dict):
        raise LabelError(
            drug, f"openfda is {type(openfda).__name__}, expected an object")
    values = openfda.get(key)
    if values is None:
        return None
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise LabelError(drug, f"openfda.{key} must be a list of strings")
    return values


def _brand_names(loaded: LoadedLabel) -> str | None:
    """Requirement 9.10: `openfda.brand_name` in snapshot order joined by ', ', or null."""
    return ", ".join(_openfda_strings(loaded, "brand_name") or ()) or None


def _class_src_name(loaded: LoadedLabel) -> str:
    """Requirements 9.5, 9.6: the first `openfda.pharm_class_epc` element verbatim, or exactly 'curated'."""
    epc = _openfda_strings(loaded, "pharm_class_epc")
    return f"curated; openFDA EPC: {epc[0]}" if epc else "curated"


def _drug_src_name(set_id: str, rxcui: str | None) -> str:
    """Requirement 9.10: names openFDA and the pinned set id, and RxNorm when RXCUI is non-null."""
    return f"openFDA label {set_id}; RxNorm {rxcui}" if rxcui is not None else f"openFDA label {set_id}"


def _rule_src_name(set_id: str, evidence: EvidencePointer) -> str:
    """Requirement 10.8: names the LABEL_SET_ID and SECTION_TYPE of the linked section."""
    return (f"Curated by MedGuard team from openFDA label {set_id}, "
            f"section {evidence.field}[{evidence.element}]")


def _in_column_order(table: str, rows: list[dict[str, Value]], columns: dict[str, list[str]]) -> list[dict[str, Value]]:
    """Each row keyed by exactly the Schema_File columns of `table`, in file order (design decision 5)."""
    if table not in columns:
        raise ValueError(f"the Schema_File defines no table {table}")
    expected = columns[table]
    ordered = []
    for row in rows:
        if set(row) != set(expected):
            missing = [c for c in expected if c not in row]
            unexpected = sorted(set(row) - set(expected))
            raise ValueError(
                f"{table}: built columns differ from the Schema_File (not built: {missing}, "
                f"not in the Schema_File: {unexpected})")
        ordered.append({column: row[column] for column in expected})
    return ordered


def build_rows(
    fx: DemoFixture,
    labels: list[LoadedLabel],
    manifest: list[ManifestEntry],
    columns: dict[str, list[str]],
) -> SeedRows:
    """Every Seed_Owned_Table row of a Default_Seed_Run, keyed by table in SEED_OWNED_TABLES order.

    `columns` maps each table to its Schema_File column names in file order; every row is a dict with
    exactly those keys in that order, and a ValueError names any drift. Values keep their Python types
    (see `to_wire`). Only fixture drugs with a Label_Manifest entry get DRUG and DRUG_CLASS rows, so the
    Optional_Drugs left out of the manifest get none (design decision 7). Every date and timestamp comes from
    the fixture, a label's `effective_time` or its Snapshot_Metadata `fetched_at` (Requirement 3.9).

    Pure: reads no clock, environment, random source or file. Expects inputs that `fixture_problems`
    accepted; it still raises ValueError for a missing label, drug or evidence section, and LabelError
    from `import_sections` or a malformed `openfda` list.
    """
    manifest_order = sorted(manifest, key=lambda entry: entry.position)
    by_drug = {loaded.entry.generic_name: loaded for loaded in _manifest_labels(
        labels, manifest)}
    for entry in manifest_order:
        if entry.generic_name not in by_drug:
            raise ValueError(
                f"{entry.generic_name}: no Label_Snapshot was loaded for this Label_Manifest entry")
    drugs = [d for d in fx.drugs if d.generic_name in by_drug]
    drug_ids = {d.generic_name: d.drug_id for d in drugs}
    for entry in manifest_order:
        if entry.generic_name not in drug_ids:
            raise ValueError(
                f"Label_Manifest drug {entry.generic_name!r} has no fixture drug entry")

    def drug_id(name: str, path: str) -> int:
        if name not in drug_ids:
            raise ValueError(
                f"{path}: drug {name!r} has no DRUG row in this run")
        return drug_ids[name]

    patient_id = fx.patient.patient_id
    consult_id = fx.consultation.consult_id
    tables: dict[str, list[dict[str, Value]]] = {
        table: [] for table in SEED_OWNED_TABLES}

    for d in drugs:
        loaded = by_drug[d.generic_name]
        tables["DRUG"].append({
            "DRUG_ID": d.drug_id, "RXCUI": d.rxcui, "GENERIC_NAME": d.generic_name,
            "BRAND_NAMES": _brand_names(loaded), "IS_OTC": d.is_otc,
            "SRC_NAME": _drug_src_name(loaded.entry.set_id, d.rxcui),
            "SOURCE_FETCHED_AT": loaded.metadata.fetched_at,
        })
    for d in drugs:
        src_name = _class_src_name(by_drug[d.generic_name])
        for c in d.classes:
            tables["DRUG_CLASS"].append({
                "DRUG_ID": d.drug_id, "CLASS_NAME": c.class_name, "CLASS_TYPE": c.class_type, "SRC_NAME": src_name,
            })
    for s in fx.class_synonyms:
        tables["CLASS_SYNONYM"].append(
            {"CLASS_NAME": s.class_name, "SYNONYM": s.synonym, "CURATED_BY": s.curated_by})

    sections: dict[tuple[str, str, int], SectionRow] = {}
    for entry in manifest_order:
        loaded = by_drug[entry.generic_name]
        effective_at = datetime.strptime(
            loaded.label["effective_time"], "%Y%m%d").date()
        for row in import_sections(loaded)[0]:
            sections[(row.generic_name, row.section_type, row.element)] = row
            tables["DRUG_LABEL_SECTION"].append({
                "SECTION_ID": row.section_id, "DRUG_ID": drug_ids[entry.generic_name],
                "SECTION_TYPE": row.section_type, "SECTION_TEXT": row.text,
                "LABEL_SET_ID": loaded.label["set_id"], "LABEL_EFFECTIVE_AT": effective_at,
                "SOURCE_URL": loaded.metadata.request_url, "SOURCE_FETCHED_AT": loaded.metadata.fetched_at,
                "CONTENT_SHA256": row.content_sha256,
            })

    for i, a in enumerate(fx.appearances):
        tables["DRUG_APPEARANCE"].append({
            "DRUG_ID": drug_id(a.drug, f"appearances[{i}].drug"), "COLOR": a.color, "SHAPE": a.shape,
            "IMPRINT": a.imprint, "STRENGTH": a.strength, "MANUFACTURER": a.manufacturer, "SRC_NAME": a.src_name,
        })
    p = fx.patient
    tables["PATIENT"].append({
        "PATIENT_ID": p.patient_id, "DISPLAY_NAME": p.display_name, "BIRTH_YEAR": p.birth_year, "SEX": p.sex,
        "PRIMARY_DX": p.primary_dx, "IS_SYNTHETIC": p.is_synthetic,
    })
    for i, m in enumerate(fx.medications):
        tables["PATIENT_MEDICATION"].append({
            "PATIENT_MED_ID": m.patient_med_id, "PATIENT_ID": patient_id,
            "DRUG_ID": drug_id(m.drug, f"medications[{i}].drug"), "STRENGTH": m.strength,
            "SCHEDULE_TEXT": m.schedule_text, "STARTED_ON": m.started_on, "STOPPED_ON": m.stopped_on,
        })
    for lab in fx.labs:
        tables["LAB_RESULT"].append({
            "LAB_ID": lab.lab_id, "PATIENT_ID": patient_id, "ANALYTE": lab.analyte, "VALUE_NUM": lab.value_num,
            "UNIT": lab.unit, "REF_LOW": lab.ref_low, "REF_HIGH": lab.ref_high, "MEASURED_AT": lab.measured_at,
        })

    for rule in fx.risk_rules:
        ev = rule.evidence
        section = sections.get((ev.drug, ev.field, ev.element))
        if section is None:
            raise ValueError(
                f"{rule.rule_name}: no imported section {ev.drug} {ev.field}[{ev.element}]")
        tables["RISK_LAB_RULE"].append({
            "RULE_ID": rule.rule_id, "RULE_NAME": rule.rule_name, "ANALYTE": rule.analyte,
            "DIRECTION": rule.direction, "CONCERN_AT": rule.concern_at, "RATIONALE": rule.rationale,
            "SRC_NAME": _rule_src_name(by_drug[ev.drug].label["set_id"], ev),
            "EVIDENCE_SECTION_ID": section.section_id, "EVIDENCE_QUOTE": rule.evidence_quote,
        })
    for rule in fx.risk_rules:
        for class_name in rule.required_classes:
            tables["RISK_RULE_CLASS"].append(
                {"RULE_ID": rule.rule_id, "CLASS_NAME": class_name})

    c = fx.consultation
    tables["CONSULTATION"].append({
        "CONSULT_ID": c.consult_id, "PATIENT_ID": patient_id, "CLINICIAN": c.clinician,
        "STARTED_AT": c.started_at, "SCENARIO": c.scenario,
    })
    for u in fx.utterances:
        tables["UTTERANCE"].append({
            "UTTERANCE_ID": u.utterance_id, "CONSULT_ID": consult_id, "SEQ": u.seq, "SPEAKER": u.speaker,
            "UTTERANCE_TEXT": u.text, "OFFSET_MS": u.offset_ms,
        })

    return {table: _in_column_order(table, rows, columns) for table, rows in tables.items()}


def to_wire(value: Value) -> int | bool | str | None:
    """The `insert_multi` form of one built value (design "Wire values for insert_multi").

    int, bool, str and None pass through; Decimal keeps its scale (`"0.97"`, `"1.20"`); a date becomes
    `YYYY-MM-DD`; a naive or UTC datetime becomes `YYYY-MM-DD HH:MM:SS.ffffff` with its wall-clock fields
    and no zone conversion (Requirement 3.9). A datetime in another zone raises ValueError, any other type
    TypeError.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() != timedelta(0):
            raise ValueError(
                f"timestamp {value.isoformat()} is not UTC; it cannot be stored without conversion")
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"no wire form for {type(value).__name__} value {value!r}")
