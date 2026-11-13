"""Unit tests for labels.py (offline: no network, no database).

Manifest and metadata: Requirements 7.1, 7.4, 7.5, 7.6, 7.10, 7.13 and 9.11.
Label_Importer (`load_label`, `import_sections`): Requirements 8.1-8.5, 8.7-8.9, 8.13, 17.3 and 17.14.
Committed snapshots end to end: Requirements 8.6, 8.9, 10.4, 10.5, 11.7 and 17.7.
"""

import ast
import hashlib
import json
import re
import shutil
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from hackathon26.evidence import verify_quote
from hackathon26.labels import (
    DEMO_DRUGS,
    IMPORTED_FIELDS,
    OPTIONAL_DRUGS,
    SET_ID_RE,
    LabelError,
    LoadedLabel,
    ManifestEntry,
    SectionRow,
    SnapshotMetadata,
    check_response,
    content_hash,
    import_sections,
    load_label,
    load_manifest,
    read_metadata,
    request_url,
    slug,
    write_metadata,
)

RAMIPRIL_SET_ID = "01da05d8-e72e-4208-bf92-a5cd929f15ab"
LABELS_MODULE = Path(__file__).resolve(
).parents[2] / "src" / "hackathon26" / "labels.py"

# Synthetic set ids, valid in form only. They identify no real openFDA document.
SET_IDS = {
    "ramipril": RAMIPRIL_SET_ID,
    "metoprolol succinate": "aaaaaaaa-2222-4333-8444-bbbbbbbbbbbb",
    "furosemide": "22222222-3333-4444-8555-666666666666",
    "ibuprofen": "33333333-4444-4555-8666-777777777777",
    "spironolactone": "44444444-5555-4666-8777-888888888888",
    "potassium chloride": "55555555-6666-4777-8888-999999999999",
}


def _write_manifest(tmp_path: Path, labels: list[dict]) -> Path:
    path = tmp_path / "label_manifest.json"
    path.write_text(json.dumps({"labels": labels}), encoding="utf-8")
    return path


def _entries(*names: str) -> list[dict]:
    return [{"generic_name": name, "set_id": SET_IDS[name]} for name in names]


# --- constants ----------------------------------------------------------------------------------


def test_constants_match_the_design():
    assert IMPORTED_FIELDS == (
        "boxed_warning", "contraindications", "warnings", "warnings_and_cautions", "drug_interactions",
    )
    assert DEMO_DRUGS == (
        "ramipril", "metoprolol succinate", "furosemide", "ibuprofen")
    assert OPTIONAL_DRUGS == ("spironolactone", "potassium chloride")
    assert SET_ID_RE == r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"


def test_label_error_names_drug_and_check():
    error = LabelError("ibuprofen", "set_id does not match the pin")
    assert error.drug == "ibuprofen"
    assert error.check == "set_id does not match the pin"
    assert "ibuprofen" in str(
        error) and "set_id does not match the pin" in str(error)


# --- load_manifest ------------------------------------------------------------------------------


def test_load_manifest_returns_entries_in_order_with_one_based_positions(tmp_path):
    names = ("ramipril", "metoprolol succinate",
             "furosemide", "ibuprofen", "spironolactone")
    entries = load_manifest(_write_manifest(tmp_path, _entries(*names)))
    assert entries == [
        ManifestEntry(generic_name=name, set_id=SET_IDS[name], position=i)
        for i, name in enumerate(names, start=1)
    ]


def test_load_manifest_accepts_demo_drugs_in_any_order(tmp_path):
    entries = load_manifest(_write_manifest(tmp_path, _entries("ibuprofen", "ramipril", "furosemide",
                                                               "metoprolol succinate")))
    assert [e.generic_name for e in entries] == [
        "ibuprofen", "ramipril", "furosemide", "metoprolol succinate"]


def test_load_manifest_rejects_a_missing_demo_drug_naming_it(tmp_path):
    path = _write_manifest(tmp_path, _entries(
        "ramipril", "metoprolol succinate", "ibuprofen"))
    with pytest.raises(LabelError) as excinfo:
        load_manifest(path)
    assert excinfo.value.drug == "furosemide"
    assert "furosemide" in str(excinfo.value)


def test_load_manifest_rejects_a_duplicate_naming_the_entry(tmp_path):
    labels = _entries("ramipril", "metoprolol succinate",
                      "furosemide", "ibuprofen", "furosemide")
    with pytest.raises(LabelError) as excinfo:
        load_manifest(_write_manifest(tmp_path, labels))
    assert excinfo.value.drug == "furosemide"
    assert "entry 5" in str(excinfo.value)
    assert "more than once" in str(excinfo.value)


def test_load_manifest_rejects_an_unknown_drug_naming_the_entry(tmp_path):
    labels = _entries(
        *DEMO_DRUGS) + [{"generic_name": "warfarin", "set_id": SET_IDS["ibuprofen"]}]
    with pytest.raises(LabelError) as excinfo:
        load_manifest(_write_manifest(tmp_path, labels))
    assert excinfo.value.drug == "warfarin"
    assert "entry 5" in str(excinfo.value)


def test_load_manifest_compares_generic_names_exactly(tmp_path):
    labels = _entries("metoprolol succinate", "furosemide", "ibuprofen") + [
        {"generic_name": "Ramipril", "set_id": RAMIPRIL_SET_ID}
    ]
    with pytest.raises(LabelError) as excinfo:
        load_manifest(_write_manifest(tmp_path, labels))
    assert excinfo.value.drug == "Ramipril"


@pytest.mark.parametrize(
    "bad_set_id",
    [
        RAMIPRIL_SET_ID.upper(),
        "01DA05D8-e72e-4208-bf92-a5cd929f15ab",
        "01da05d8e72e4208bf92a5cd929f15ab",
        "01da05d8-e72e-4208-bf92-a5cd929f15a",
        "01da05d8-e72e-4208-bf92-a5cd929f15abc",
        "01da05d8-e72e-4208-bf92-a5cd929f15ag",
        " 01da05d8-e72e-4208-bf92-a5cd929f15ab",
        "01da05d8-e72e-4208-bf92-a5cd929f15ab\n",
        "{01da05d8-e72e-4208-bf92-a5cd929f15ab}",
        "",
    ],
)
def test_load_manifest_rejects_a_malformed_or_uppercase_set_id_naming_the_entry(tmp_path, bad_set_id):
    labels = _entries("metoprolol succinate", "furosemide", "ibuprofen") + [
        {"generic_name": "ramipril", "set_id": bad_set_id}
    ]
    with pytest.raises(LabelError) as excinfo:
        load_manifest(_write_manifest(tmp_path, labels))
    assert excinfo.value.drug == "ramipril"
    assert "entry 4" in str(excinfo.value)
    assert repr(bad_set_id) in str(excinfo.value)


@pytest.mark.parametrize(
    "document",
    [
        "not json",
        "[]",
        '{"labels": {}}',
        '{"entries": []}',
        '{"labels": ["ramipril"]}',
        '{"labels": [{"generic_name": "ramipril"}]}',
        '{"labels": [{"generic_name": 1, "set_id": "01da05d8-e72e-4208-bf92-a5cd929f15ab"}]}',
    ],
)
def test_load_manifest_rejects_a_malformed_document(tmp_path, document):
    path = tmp_path / "label_manifest.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(LabelError):
        load_manifest(path)


def test_load_manifest_rejects_a_missing_file(tmp_path):
    with pytest.raises(LabelError):
        load_manifest(tmp_path / "absent.json")


# --- slug and request_url -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("metoprolol succinate", "metoprolol-succinate"),
        ("potassium chloride", "potassium-chloride"),
        ("ramipril", "ramipril"),
    ],
)
def test_slug(name, expected):
    assert slug(name) == expected


def test_request_url_matches_set_id_exactly_with_a_single_search_parameter():
    assert request_url(RAMIPRIL_SET_ID) == (
        "https://api.fda.gov/drug/label.json?search=set_id%3A%2201da05d8-e72e-4208-bf92-a5cd929f15ab%22"
    )


def test_request_url_has_no_api_key():
    assert "api_key" not in request_url(RAMIPRIL_SET_ID)


def test_labels_module_imports_only_urllib_parse_from_urllib():
    tree = ast.parse(LABELS_MODULE.read_text(encoding="utf-8"))
    urllib_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            urllib_modules |= {a.name for a in node.names if a.name.split(".")[
                0] == "urllib"}
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "urllib":
            urllib_modules.add(node.module)
            if node.module == "urllib":
                urllib_modules |= {f"urllib.{a.name}" for a in node.names}
    assert urllib_modules == {"urllib.parse"}


# --- write_metadata / read_metadata -------------------------------------------------------------

META = SnapshotMetadata(
    request_url=request_url(RAMIPRIL_SET_ID),
    fetched_at=datetime(2026, 11, 13, 21, 4, 17, tzinfo=UTC),
    sha256="a" * 64,
)

EXPECTED_META_TEXT = (
    "{\n"
    '  "fetched_at": "2026-11-13T21:04:17Z",\n'
    '  "request_url": "https://api.fda.gov/drug/label.json?search=set_id%3A%2201da05d8-e72e-4208-bf92-a5cd929f15ab%22",\n'
    '  "sha256": "' + "a" * 64 + '"\n'
    "}\n"
)


def test_write_metadata_uses_the_exact_json_form(tmp_path):
    path = tmp_path / "ramipril.meta.json"
    write_metadata(path, META)
    assert path.read_bytes() == EXPECTED_META_TEXT.encode("utf-8")


def test_read_metadata_round_trips_and_returns_utc_aware_datetime(tmp_path):
    path = tmp_path / "ramipril.meta.json"
    write_metadata(path, META)
    meta = read_metadata(path)
    assert meta == META
    assert meta.fetched_at.utcoffset() == timedelta(0)


def test_read_metadata_parses_the_committed_form(tmp_path):
    path = tmp_path / "ramipril.meta.json"
    path.write_text(EXPECTED_META_TEXT, encoding="utf-8")
    assert read_metadata(path) == META


@pytest.mark.parametrize(
    "bad_meta",
    [
        SnapshotMetadata(META.request_url, datetime(
            2026, 11, 13, 21, 4, 17), META.sha256),
        SnapshotMetadata(META.request_url, datetime(
            2026, 11, 13, 21, 4, 17, 5, tzinfo=UTC), META.sha256),
        SnapshotMetadata(META.request_url, datetime(2026, 11, 13, 22, 4, 17,
                                                    tzinfo=timezone(timedelta(hours=1))), META.sha256),
        SnapshotMetadata("", META.fetched_at, META.sha256),
        SnapshotMetadata(META.request_url, META.fetched_at, "A" * 64),
    ],
)
def test_write_metadata_refuses_a_record_it_could_not_read_back(tmp_path, bad_meta):
    path = tmp_path / "x.meta.json"
    with pytest.raises(ValueError):
        write_metadata(path, bad_meta)
    assert not path.exists()


def _meta_file(tmp_path: Path, **overrides) -> Path:
    record = {"fetched_at": "2026-11-13T21:04:17Z",
              "request_url": META.request_url, "sha256": "a" * 64}
    record.update(overrides)
    path = tmp_path / "ramipril.meta.json"
    path.write_text(json.dumps(record, indent=2,
                    sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_read_metadata_rejects_an_empty_url(tmp_path):
    with pytest.raises(LabelError) as excinfo:
        read_metadata(_meta_file(tmp_path, request_url=""), drug="ramipril")
    assert excinfo.value.drug == "ramipril"
    assert "request_url" in str(excinfo.value)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-11-13 21:04:17Z",
        "2026-11-13T21:04:17",
        "2026-11-13T21:04:17+00:00",
        "2026-11-13T21:04:17.000Z",
        "2026-11-13T21:04Z",
        "2026-02-30T21:04:17Z",
        "2026-11-13T25:04:17Z",
        "",
        12345,
    ],
)
def test_read_metadata_rejects_a_bad_timestamp(tmp_path, timestamp):
    with pytest.raises(LabelError) as excinfo:
        read_metadata(_meta_file(tmp_path, fetched_at=timestamp))
    assert "fetched_at" in str(excinfo.value)


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", None])
def test_read_metadata_rejects_a_bad_sha256(tmp_path, digest):
    with pytest.raises(LabelError) as excinfo:
        read_metadata(_meta_file(tmp_path, sha256=digest))
    assert "sha256" in str(excinfo.value)


def test_read_metadata_rejects_missing_extra_keys_and_invalid_json(tmp_path):
    path = tmp_path / "ramipril.meta.json"
    path.write_text(
        '{"fetched_at": "2026-11-13T21:04:17Z", "sha256": "' + "a" * 64 + '"}', encoding="utf-8")
    with pytest.raises(LabelError):
        read_metadata(path)
    with pytest.raises(LabelError):
        read_metadata(_meta_file(tmp_path, extra="x"))
    path.write_text("{", encoding="utf-8")
    with pytest.raises(LabelError):
        read_metadata(path)


def test_read_metadata_of_a_missing_file_names_the_fetcher_command(tmp_path):
    with pytest.raises(LabelError) as excinfo:
        read_metadata(tmp_path / "ramipril.meta.json", drug="ramipril")
    assert excinfo.value.drug == "ramipril"
    assert "uv run python scripts/fetch_labels.py" in str(excinfo.value)


# --- check_response -----------------------------------------------------------------------------

ENTRY = ManifestEntry(generic_name="metoprolol succinate",
                      set_id=SET_IDS["metoprolol succinate"], position=2)


def _label(**overrides) -> dict:
    label = {
        "set_id": ENTRY.set_id,
        "effective_time": "20240101",
        "openfda": {"generic_name": ["METOPROLOL SUCCINATE"]},
    }
    label.update(overrides)
    return label


def _body(total=1, results=None, **label_overrides) -> bytes:
    if results is None:
        results = [_label(**label_overrides)]
    return json.dumps({"meta": {"results": {"skip": 0, "limit": 1, "total": total}}, "results": results}).encode()


def test_check_response_accepts_a_matching_body_and_returns_the_label():
    assert check_response(ENTRY, _body()) == _label()


def test_check_response_matches_generic_name_case_insensitively_as_a_substring():
    body = _body(openfda={"generic_name": [
                 "ACETAMINOPHEN", "Metoprolol Succinate Extended-Release"]})
    assert check_response(ENTRY, body)["set_id"] == ENTRY.set_id


@pytest.mark.parametrize(
    ("body", "check_fragment"),
    [
        (b"not json", "JSON"),
        (b"\xff\xfe", "JSON"),
        (b"[]", "meta.results.total"),
        (json.dumps({"results": [_label()]}).encode(), "meta.results.total"),
        (_body(total=0, results=[]), "meta.results.total"),
        (_body(total=2), "meta.results.total"),
        (_body(total=True), "meta.results.total"),
        (_body(total="1"), "meta.results.total"),
        (_body(results=[]), "results"),
        (_body(results=[_label(), _label()]), "results"),
        (_body(results=["x"]), "results"),
        (_body(set_id=SET_IDS["furosemide"]), "set_id"),
        (_body(set_id=ENTRY.set_id.upper()), "set_id"),
        (json.dumps({"meta": {"results": {"total": 1}},
                     "results": [{"openfda": {"generic_name": ["METOPROLOL SUCCINATE"]}}]}).encode(), "set_id"),
        (_body(openfda={"generic_name": [
         "METOPROLOL TARTRATE"]}), "generic_name"),
        (_body(openfda={"generic_name": []}), "generic_name"),
        (_body(openfda={"generic_name": "METOPROLOL SUCCINATE"}),
         "generic_name"),
        (_body(openfda={}), "generic_name"),
        (_body(openfda=None), "generic_name"),
    ],
)
def test_check_response_rejects_a_body_that_fails_a_check(body, check_fragment):
    with pytest.raises(LabelError) as excinfo:
        check_response(ENTRY, body)
    assert excinfo.value.drug == ENTRY.generic_name
    assert check_fragment in excinfo.value.check


# --- content_hash -------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "ACE inhibitors", "Nichtsteroidale Antirheumatika – Ödeme ≥ 5 µg\n"])
def test_content_hash_is_sha256_of_utf8_bytes(text):
    assert content_hash(text) == hashlib.sha256(
        text.encode("utf-8")).hexdigest()


def test_content_hash_rejects_text_that_cannot_be_encoded_naming_drug_and_field():
    with pytest.raises(LabelError) as excinfo:
        content_hash("bad \ud800 text", drug="ramipril", field="warnings")
    assert excinfo.value.drug == "ramipril"
    assert "warnings" in str(excinfo.value)


# --- committed Label_Manifest, Label_Snapshots and Snapshot_Metadata ------------------------------
# These read the real committed files under data/reference/. A missing file is a failure, not a skip
# (Requirements 7.10, 17.6, 17.7).

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference"
COMMITTED_MANIFEST = REFERENCE_DIR / "label_manifest.json"
COMMITTED_LABEL_DIR = REFERENCE_DIR / "labels"


def test_committed_manifest_pins_every_demo_drug_and_ramipril():
    entries = load_manifest(COMMITTED_MANIFEST)
    pins = {e.generic_name: e.set_id for e in entries}
    assert set(DEMO_DRUGS) <= set(pins)
    assert pins["ramipril"] == RAMIPRIL_SET_ID


def test_every_manifest_entry_has_a_committed_snapshot_and_metadata_file():
    missing = []
    for entry in load_manifest(COMMITTED_MANIFEST):
        stem = slug(entry.generic_name)
        for path in (COMMITTED_LABEL_DIR / f"{stem}.json", COMMITTED_LABEL_DIR / f"{stem}.meta.json"):
            if not path.is_file():
                missing.append(
                    f"{entry.generic_name}: {path.relative_to(REFERENCE_DIR)}")
    assert not missing, (
        "missing committed label files (run uv run python scripts/fetch_labels.py): " +
        "; ".join(missing)
    )


def test_every_committed_snapshot_metadata_round_trips(tmp_path):
    entries = load_manifest(COMMITTED_MANIFEST)
    committed = sorted(COMMITTED_LABEL_DIR.glob("*.meta.json"))
    drug_by_file = {f"{slug(e.generic_name)}.meta.json": e for e in entries}
    present = {p.name for p in committed}
    absent = [e.generic_name for name,
              e in drug_by_file.items() if name not in present]
    assert not absent, f"Snapshot_Metadata missing for: {', '.join(absent)}"
    for path in committed:
        entry = drug_by_file.get(path.name)
        drug = entry.generic_name if entry else path.name
        meta = read_metadata(path, drug=drug)
        copy = tmp_path / path.name
        write_metadata(copy, meta)
        assert read_metadata(
            copy, drug=drug) == meta, f"{drug}: Snapshot_Metadata does not round-trip"
        assert copy.read_bytes() == path.read_bytes(
        ), f"{drug}: committed form differs from write_metadata output"
        if entry is not None:
            assert meta.request_url == request_url(
                entry.set_id), f"{drug}: request_url is not the pinned set id URL"
            snapshot = COMMITTED_LABEL_DIR / f"{slug(entry.generic_name)}.json"
            assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == meta.sha256, (
                f"{drug}: SHA-256 of {snapshot.name} differs from its Snapshot_Metadata"
            )


# --- Label_Importer: load_label and import_sections -----------------------------------------------
# These use only the synthetic fixture under tests/fixtures/labels/ (Requirement 17.3). Examplamide is a
# fictional drug, and its set id identifies no real openFDA document.

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "labels"
FIXTURE_SNAPSHOT = FIXTURE_DIR / "examplamide.json"
FIXTURE_META = FIXTURE_DIR / "examplamide.meta.json"
FIXTURE_DRUG = "examplamide"
FIXTURE_SET_ID = "e0e0e0e0-1111-4222-8333-444444444444"
FIXTURE_ENTRY = ManifestEntry(
    generic_name=FIXTURE_DRUG, set_id=FIXTURE_SET_ID, position=1)
FETCH_COMMAND_TEXT = "uv run python scripts/fetch_labels.py"

# Written out by hand so exactness does not depend on the importer's own decoding.
CONTRAINDICATIONS_0 = (
    "  4 CONTRAINDICATIONS\nExamplamide is contraindicated in patients with a history of hypersensitivity "
    "to examplamide or to any excipient.  "
)
WARNINGS_AND_CAUTIONS_2 = (
    "\t5.2 Hyperkalemia: concomitant use with potassium-sparing diuretics may increase serum potassium "
    "≥ 5,5 mmol/L.\r\nFrançais : hyperkaliémie possible."
)


@pytest.fixture
def no_database(monkeypatch):
    """Fail the test if anything tries to open a database connection."""
    import hackathon26.db as db

    def refuse(*args, **kwargs):
        raise AssertionError("a label check opened a database connection")

    monkeypatch.setattr(db, "connect", refuse)


def _fixture_label() -> dict:
    return json.loads(FIXTURE_SNAPSHOT.read_text(encoding="utf-8"))["results"][0]


def _fixture_meta() -> SnapshotMetadata:
    return read_metadata(FIXTURE_META)


def _loaded(label: dict, position: int = 1) -> LoadedLabel:
    entry = ManifestEntry(generic_name=FIXTURE_DRUG,
                          set_id=FIXTURE_SET_ID, position=position)
    return LoadedLabel(entry=entry, label=label, metadata=_fixture_meta())


def _stage(tmp_path: Path, *, document=None, raw: bytes | None = None, meta: bool = True,
           snapshot: bool = True, sha256: str | None = None) -> Path:
    """Write examplamide.json (and its metadata, with a matching SHA-256 unless given) into tmp_path."""
    if raw is None:
        raw = (FIXTURE_SNAPSHOT.read_bytes() if document is None
               else json.dumps(document, ensure_ascii=False).encode("utf-8"))
    if snapshot:
        (tmp_path / "examplamide.json").write_bytes(raw)
    if meta:
        record = _fixture_meta()
        digest = sha256 if sha256 is not None else hashlib.sha256(
            raw).hexdigest()
        write_metadata(tmp_path / "examplamide.meta.json",
                       SnapshotMetadata(record.request_url, record.fetched_at, digest))
    return tmp_path


def _fixture_document(**label_changes) -> dict:
    document = json.loads(FIXTURE_SNAPSHOT.read_text(encoding="utf-8"))
    for key, value in label_changes.items():
        if value is _ABSENT:
            document["results"][0].pop(key)
        else:
            document["results"][0][key] = value
    return document


_ABSENT = object()


def test_fixture_meets_the_shape_requirement_17_3():
    raw = FIXTURE_SNAPSHOT.read_bytes()
    assert len(raw) <= 20 * 1024
    assert hashlib.sha256(raw).hexdigest() == _fixture_meta().sha256
    label = _fixture_label()
    present = [f for f in IMPORTED_FIELDS if f in label]
    assert len(present) >= 2
    assert any(len(label[f]) >= 2 for f in present)
    assert any(e == "" for f in present for e in label[f])
    assert "indications_and_usage" in label and "indications_and_usage" not in IMPORTED_FIELDS
    texts = [e for f in present for e in label[f] if e]
    assert any(t != t.strip() for t in texts)
    assert any("\n" in t for t in texts)
    assert any(not t.isascii() for t in texts)


# load_label --------------------------------------------------------------------------------------


def test_load_label_returns_the_single_label_with_its_entry_and_metadata(no_database):
    loaded = load_label(FIXTURE_ENTRY, FIXTURE_DIR)
    assert loaded == LoadedLabel(
        entry=FIXTURE_ENTRY, label=_fixture_label(), metadata=_fixture_meta())


def test_load_label_reports_a_missing_snapshot_with_the_fetcher_command(tmp_path, no_database):
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(tmp_path, snapshot=False))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "missing" in excinfo.value.check
    assert FETCH_COMMAND_TEXT in str(excinfo.value)


def test_load_label_reports_missing_metadata_with_the_fetcher_command(tmp_path, no_database):
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(tmp_path, meta=False))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "Snapshot_Metadata" in excinfo.value.check and "missing" in excinfo.value.check
    assert FETCH_COMMAND_TEXT in str(excinfo.value)


def test_load_label_reports_a_sha256_mismatch_with_the_fetcher_command(tmp_path, no_database):
    shutil.copy(FIXTURE_META, tmp_path / "examplamide.meta.json")
    (tmp_path / "examplamide.json").write_bytes(FIXTURE_SNAPSHOT.read_bytes() + b" ")
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, tmp_path)
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "SHA-256" in excinfo.value.check
    assert FETCH_COMMAND_TEXT in str(excinfo.value)


@pytest.mark.parametrize("raw", [b"{", b"\xff\xfe{}"])
def test_load_label_reports_invalid_json(tmp_path, no_database, raw):
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(tmp_path, raw=raw))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "JSON" in excinfo.value.check


@pytest.mark.parametrize(
    "results",
    [[], [_ABSENT, _ABSENT], None, ["not a label"]],
    ids=["zero", "two", "absent", "not-an-object"],
)
def test_load_label_requires_exactly_one_result(tmp_path, no_database, results):
    document = _fixture_document()
    label = document["results"][0]
    if results is None:
        document.pop("results")
    else:
        document["results"] = [label if r is _ABSENT else r for r in results]
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(tmp_path, document=document))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "results" in excinfo.value.check


def test_load_label_requires_a_set_id(tmp_path, no_database):
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(
            tmp_path, document=_fixture_document(set_id=_ABSENT)))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "no set_id" in excinfo.value.check


@pytest.mark.parametrize("set_id", ["aaaaaaaa-1111-4222-8333-444444444444", FIXTURE_SET_ID.upper(), None])
def test_load_label_requires_the_pinned_set_id(tmp_path, no_database, set_id):
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(
            tmp_path, document=_fixture_document(set_id=set_id)))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "pinned set id" in excinfo.value.check
    assert FIXTURE_SET_ID in excinfo.value.check


@pytest.mark.parametrize(
    "effective_time",
    ["2024022", "202402291", "2024-02-29", "20230229", "20241301", "20240100", " 20240229",
     "２０２４０２２９", 20240229, None, _ABSENT],
)
def test_load_label_requires_an_8_digit_calendar_effective_time(tmp_path, no_database, effective_time):
    document = _fixture_document(effective_time=effective_time)
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, _stage(tmp_path, document=document))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "effective_time" in excinfo.value.check


def test_load_label_checks_in_order_sha256_before_json(tmp_path, no_database):
    _stage(tmp_path, raw=b"{", sha256="0" * 64)
    with pytest.raises(LabelError) as excinfo:
        load_label(FIXTURE_ENTRY, tmp_path)
    assert "SHA-256" in excinfo.value.check


# import_sections ---------------------------------------------------------------------------------


def test_import_sections_yields_one_row_per_non_empty_element_with_exact_text():
    rows, notices = import_sections(load_label(FIXTURE_ENTRY, FIXTURE_DIR))
    label = _fixture_label()
    assert [(r.section_type, r.element) for r in rows] == [
        ("contraindications", 0),
        ("warnings_and_cautions", 0),
        ("warnings_and_cautions", 2),
        ("drug_interactions", 0),
    ]
    for row in rows:
        assert row.generic_name == FIXTURE_DRUG
        assert row.text == label[row.section_type][row.element]
    assert rows[0].text == CONTRAINDICATIONS_0
    assert rows[2].text == WARNINGS_AND_CAUTIONS_2
    assert all(r.section_type != "indications_and_usage" for r in rows)
    assert all(r.text for r in rows)
    assert notices == [
        f"{FIXTURE_DRUG}: empty warnings_and_cautions element skipped"]


def test_import_sections_numbers_sections_by_manifest_field_and_element():
    rows, _ = import_sections(_loaded(_fixture_label(), position=1))
    assert [r.section_id for r in rows] == [1200, 1400, 1402, 1500]
    later, _ = import_sections(_loaded(_fixture_label(), position=3))
    assert [r.section_id for r in later] == [3200, 3400, 3402, 3500]
    ids = [r.section_id for r in rows + later]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_section_id_formula_puts_drug_interactions_at_1500_and_warnings_and_cautions_at_1400():
    label = {"warnings_and_cautions": [
        "w"], "drug_interactions": ["d"], "boxed_warning": ["b"]}
    rows, _ = import_sections(_loaded(label, position=1))
    assert {(r.section_type, r.element): r.section_id for r in rows} == {
        ("boxed_warning", 0): 1100,
        ("warnings_and_cautions", 0): 1400,
        ("drug_interactions", 0): 1500,
    }


def test_import_sections_hashes_match_an_independent_sha256():
    rows, _ = import_sections(load_label(FIXTURE_ENTRY, FIXTURE_DIR))
    for row in rows:
        assert row.content_sha256 == hashlib.sha256(
            row.text.encode("utf-8")).hexdigest()
        assert len(
            row.content_sha256) == 64 and row.content_sha256 == row.content_sha256.lower()


def test_import_sections_returns_section_rows():
    rows, _ = import_sections(load_label(FIXTURE_ENTRY, FIXTURE_DIR))
    assert rows[0] == SectionRow(
        section_id=1200,
        generic_name=FIXTURE_DRUG,
        section_type="contraindications",
        element=0,
        text=CONTRAINDICATIONS_0,
        content_sha256=hashlib.sha256(
            CONTRAINDICATIONS_0.encode("utf-8")).hexdigest(),
    )


def test_import_sections_notices_a_label_with_zero_imported_sections():
    label = {"set_id": FIXTURE_SET_ID,
             "indications_and_usage": ["text"], "warnings": [""]}
    rows, notices = import_sections(_loaded(label))
    assert rows == []
    assert notices == [
        f"{FIXTURE_DRUG}: empty warnings element skipped",
        f"no label sections were imported for {FIXTURE_DRUG}",
    ]


def test_import_sections_rejects_an_element_index_of_100_or_more():
    label = {"drug_interactions": ["x"] * 101}
    with pytest.raises(LabelError) as excinfo:
        import_sections(_loaded(label))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "drug_interactions" in excinfo.value.check and "100" in excinfo.value.check


def test_import_sections_accepts_100_elements():
    rows, _ = import_sections(_loaded({"drug_interactions": ["x"] * 100}))
    assert rows[-1].section_id == 1599


def test_import_sections_rejects_a_lone_surrogate_naming_drug_and_field(tmp_path):
    raw = FIXTURE_SNAPSHOT.read_bytes().replace(
        b"5.2 Hyperkalemia", b"5.2 \\ud800 Hyperkalemia")
    loaded = load_label(FIXTURE_ENTRY, _stage(tmp_path, raw=raw))
    with pytest.raises(LabelError) as excinfo:
        import_sections(loaded)
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "warnings_and_cautions" in excinfo.value.check


@pytest.mark.parametrize("value", ["a string", {"0": "x"}, None, ["ok", 7]])
def test_import_sections_rejects_a_field_that_is_not_a_list_of_strings(value):
    with pytest.raises(LabelError) as excinfo:
        import_sections(_loaded({"warnings": value}))
    assert excinfo.value.drug == FIXTURE_DRUG
    assert "warnings" in excinfo.value.check


# --- committed Label_Snapshots end to end (Requirements 8.6, 8.9, 10.4, 10.5, 11.7, 17.7) ---------
# Imports every committed Label_Snapshot with the Label_Importer. A missing or failing snapshot is a
# test failure that names the drug, never a skip.

TRIPLE_WHAMMY_QUOTE = (
    "In patients who are elderly, volume-depleted (including those on diuretic therapy), or with "
    "compromised renal function, co-administration of NSAIDs, including selective COX-2 inhibitors, with "
    "ACE inhibitors, including ramipril, may result in deterioration of renal function, including possible "
    "acute renal failure."
)
POTASSIUM_QUOTE = (
    "Risk factors for the development of hyperkalemia include renal insufficiency, diabetes mellitus, and "
    "the concomitant use of potassium-sparing diuretics, potassium supplements, and/or potassium-containing "
    "salt substitutes"
)
_LOWER_HEX_64 = re.compile(r"\A[0-9a-f]{64}\Z")


def _import_committed() -> dict[str, tuple[LoadedLabel, list[SectionRow]]]:
    """Run load_label + import_sections on every Label_Manifest entry; fail naming the drug on any error."""
    imported = {}
    for entry in load_manifest(COMMITTED_MANIFEST):
        try:
            loaded = load_label(entry, COMMITTED_LABEL_DIR)
            rows, _ = import_sections(loaded)
        except LabelError as exc:
            pytest.fail(
                f"committed Label_Snapshot for {exc.drug} failed: {exc.check}")
        imported[entry.generic_name] = (loaded, rows)
    return imported


def test_every_committed_snapshot_imports_rows_equal_to_the_source_and_hashed(no_database):
    imported = _import_committed()
    assert set(DEMO_DRUGS) <= set(imported)
    for drug, (loaded, rows) in imported.items():
        assert rows, f"{drug}: no label sections were imported"
        # Decode the snapshot independently of load_label, so the comparison does not reuse its result.
        snapshot = COMMITTED_LABEL_DIR / f"{slug(drug)}.json"
        source = json.loads(
            snapshot.read_bytes().decode("utf-8"))["results"][0]
        for row in rows:
            where = f"{drug} {row.section_type}[{row.element}] (SECTION_ID {row.section_id})"
            assert row.generic_name == drug, where
            assert row.text == source[row.section_type][
                row.element], f"{where}: text differs from snapshot"
            assert _LOWER_HEX_64.match(
                row.content_sha256), f"{where}: hash is not 64 lowercase hex"
            assert row.content_sha256 == hashlib.sha256(row.text.encode("utf-8")).hexdigest(), (
                f"{where}: CONTENT_SHA256 differs from SHA-256 of SECTION_TEXT"
            )
        ids = [r.section_id for r in rows]
        assert len(set(ids)) == len(ids), f"{drug}: duplicate SECTION_IDs"


def test_committed_section_ids_are_unique_across_all_drugs(no_database):
    ids = [r.section_id for _, rows in _import_committed().values()
           for r in rows]
    assert len(set(ids)) == len(ids)


def _ramipril() -> tuple[LoadedLabel, dict[int, SectionRow]]:
    loaded, rows = _import_committed()["ramipril"]
    return loaded, {r.section_id: r for r in rows}


def test_ramipril_provenance_and_linked_section_ids(no_database):
    loaded, by_id = _ramipril()
    assert loaded.entry.position == 1
    assert loaded.label["set_id"] == RAMIPRIL_SET_ID
    # LABEL_EFFECTIVE_AT is the date parsed from effective_time in YYYYMMDD form (Requirement 8.6).
    assert loaded.label["effective_time"] == "20220701"
    assert datetime.strptime(
        loaded.label["effective_time"], "%Y%m%d").date() == date(2022, 7, 1)
    assert loaded.metadata.request_url == request_url(RAMIPRIL_SET_ID)
    assert (by_id[1500].section_type, by_id[1500].element) == (
        "drug_interactions", 0)
    assert (by_id[1400].section_type, by_id[1400].element) == (
        "warnings_and_cautions", 0)


@pytest.mark.parametrize(
    ("section_id", "section_type", "quote"),
    [
        (1500, "drug_interactions", TRIPLE_WHAMMY_QUOTE),
        (1400, "warnings_and_cautions", POTASSIUM_QUOTE),
    ],
    ids=["triple-whammy-10.4", "potassium-10.5"],
)
def test_verify_quote_accepts_the_curated_quotes_against_the_ramipril_sections(
        no_database, section_id, section_type, quote):
    _, by_id = _ramipril()
    row = by_id[section_id]
    assert verify_quote(quote, row.text), (
        f"quote not found: LABEL_SET_ID {RAMIPRIL_SET_ID}, SECTION_TYPE {section_type}, SECTION_ID {section_id}"
    )
