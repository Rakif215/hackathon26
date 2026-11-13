"""Label_Manifest, Snapshot_Metadata, openFDA response checks and the Label_Importer (no network, no database).

Shared by the Label_Fetcher (`scripts/fetch_labels.py`) and the Seed_Command. The only `urllib`
module imported here is `urllib.parse`, which formats strings and opens no connection.
"""

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

IMPORTED_FIELDS = ("boxed_warning", "contraindications",
                   "warnings", "warnings_and_cautions", "drug_interactions")
DEMO_DRUGS = ("ramipril", "metoprolol succinate", "furosemide", "ibuprofen")
OPTIONAL_DRUGS = ("spironolactone", "potassium chloride")
SET_ID_RE = r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"

FETCH_COMMAND = "uv run python scripts/fetch_labels.py"
OPENFDA_LABEL_ENDPOINT = "https://api.fda.gov/drug/label.json"

_SHA256_RE = r"\A[0-9a-f]{64}\Z"
_TIMESTAMP_RE = r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z"
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_METADATA_KEYS = frozenset({"request_url", "fetched_at", "sha256"})
_MANIFEST_KEYS = frozenset({"generic_name", "set_id"})
_MANIFEST_DOCUMENT = "label manifest"
_EFFECTIVE_TIME_RE = r"\A[0-9]{8}\Z"
# SECTION_ID gives each field 100 element slots (e = 0..99)
_MAX_ELEMENTS = 100


class LabelError(Exception):
    """A label input failed a check. `drug` names the drug (or file) and `check` the failed check."""

    def __init__(self, drug: str, check: str) -> None:
        super().__init__(f"{drug}: {check}")
        self.drug = drug
        self.check = check


@dataclass(frozen=True)
class ManifestEntry:
    generic_name: str
    set_id: str
    position: int  # 1-based order in the Label_Manifest


@dataclass(frozen=True)
class SnapshotMetadata:
    request_url: str
    fetched_at: datetime  # UTC-aware, second precision
    sha256: str  # lowercase hex SHA-256 of the Label_Snapshot file bytes


@dataclass(frozen=True)
class LoadedLabel:
    """A Label_Snapshot that passed the seed-time checks: its manifest entry, its single label, its metadata."""

    entry: ManifestEntry
    label: dict  # the single element of the snapshot's `results` array
    metadata: SnapshotMetadata


@dataclass(frozen=True)
class SectionRow:
    """One DRUG_LABEL_SECTION row before DRUG_ID and provenance columns are attached."""

    # 1000 * manifest position + 100 * (1-based IMPORTED_FIELDS index) + element index
    section_id: int
    generic_name: str
    section_type: str  # one of IMPORTED_FIELDS
    element: int  # 0-based position in the snapshot's field list
    text: str  # exactly the JSON-decoded element
    content_sha256: str


def _is_set_id(value: object) -> bool:
    return isinstance(value, str) and re.match(SET_ID_RE, value) is not None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.match(_SHA256_RE, value) is not None


def slug(generic_name: str) -> str:
    """File-name stem for a drug: "metoprolol succinate" -> "metoprolol-succinate"."""
    return re.sub(r"[^a-z0-9]+", "-", generic_name.lower()).strip("-")


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read and validate the Label_Manifest (Requirements 7.1, 7.13, 9.11).

    Raises LabelError naming the entry at fault, or the Demo_Drug that has no entry.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LabelError(_MANIFEST_DOCUMENT,
                         f"file {path} is missing") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LabelError(_MANIFEST_DOCUMENT,
                         f"file {path} is not valid JSON: {exc}") from None
    if not isinstance(document, dict) or set(document) != {"labels"} or not isinstance(document["labels"], list):
        raise LabelError(
            _MANIFEST_DOCUMENT, 'expected an object with exactly one key "labels" holding a list')

    known = DEMO_DRUGS + OPTIONAL_DRUGS
    entries: list[ManifestEntry] = []
    seen: dict[str, int] = {}
    for position, raw in enumerate(document["labels"], start=1):
        where = f"entry {position}"
        if not isinstance(raw, dict) or set(raw) != _MANIFEST_KEYS:
            raise LabelError(
                _MANIFEST_DOCUMENT, f'{where} {raw!r}: expected exactly the keys "generic_name" and "set_id"')
        name, set_id = raw["generic_name"], raw["set_id"]
        if not isinstance(name, str):
            raise LabelError(_MANIFEST_DOCUMENT,
                             f"{where}: generic_name {name!r} is not a string")
        if name not in known:
            raise LabelError(
                name, f"{where} {raw!r}: {name!r} is neither a Demo_Drug nor an Optional_Drug")
        if name in seen:
            raise LabelError(
                name, f"{where} {raw!r}: {name!r} is listed more than once (first at entry {seen[name]})")
        if not _is_set_id(set_id):
            raise LabelError(
                name, f"{where} {raw!r}: set id {set_id!r} is not a lowercase 8-4-4-4-12 hexadecimal identifier"
            )
        seen[name] = position
        entries.append(ManifestEntry(generic_name=name,
                       set_id=set_id, position=position))

    for drug in DEMO_DRUGS:
        if drug not in seen:
            raise LabelError(
                drug, f"the Label_Manifest {path} has no entry for Demo_Drug {drug!r}")
    return entries


def request_url(set_id: str) -> str:
    """The openFDA label URL whose single `search` parameter matches `set_id` exactly. Builds a string only."""
    if not _is_set_id(set_id):
        raise ValueError(
            f"not a lowercase 8-4-4-4-12 hexadecimal set id: {set_id!r}")
    return f"{OPENFDA_LABEL_ENDPOINT}?{urllib.parse.urlencode({'search': f'set_id:"{set_id}"'})}"


def _metadata_problem(meta: SnapshotMetadata) -> str | None:
    if not isinstance(meta.request_url, str) or not meta.request_url:
        return "request_url must be a non-empty string"
    at = meta.fetched_at
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() != timedelta(0):
        return "fetched_at must be a UTC-aware datetime"
    if at.microsecond:
        return "fetched_at must have second precision"
    if not _is_sha256(meta.sha256):
        return "sha256 must be 64 lowercase hexadecimal characters"
    return None


def write_metadata(path: Path, meta: SnapshotMetadata) -> None:
    """Write Snapshot_Metadata as sorted, 2-space-indented JSON with a trailing newline.

    Raises ValueError, writing nothing, for a record that `read_metadata` would reject.
    """
    problem = _metadata_problem(meta)
    if problem:
        raise ValueError(
            f"refusing to write Snapshot_Metadata {path}: {problem}")
    record = {
        "fetched_at": meta.fetched_at.strftime(_TIMESTAMP_FORMAT),
        "request_url": meta.request_url,
        "sha256": meta.sha256,
    }
    text = json.dumps(record, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"
    Path(path).write_bytes(text.encode("utf-8"))


def read_metadata(path: Path, *, drug: str | None = None) -> SnapshotMetadata:
    """Read Snapshot_Metadata written by `write_metadata`. Raises LabelError naming `drug` (or the file)."""
    path = Path(path)
    who = drug if drug is not None else path.name
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LabelError(
            who, f"Snapshot_Metadata file {path} is missing; run {FETCH_COMMAND}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LabelError(
            who, f"Snapshot_Metadata file {path} is not valid JSON: {exc}") from None
    if not isinstance(record, dict) or set(record) != _METADATA_KEYS:
        raise LabelError(
            who, f"Snapshot_Metadata {path} must have exactly the keys fetched_at, request_url, sha256")

    url, stamp, digest = record["request_url"], record["fetched_at"], record["sha256"]
    if not isinstance(url, str) or not url:
        raise LabelError(
            who, f"Snapshot_Metadata {path}: request_url must be a non-empty string")
    if not isinstance(stamp, str) or re.match(_TIMESTAMP_RE, stamp) is None:
        raise LabelError(
            who, f"Snapshot_Metadata {path}: fetched_at {stamp!r} is not YYYY-MM-DDTHH:MM:SSZ")
    try:
        fetched_at = datetime.strptime(
            stamp, _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        raise LabelError(
            who, f"Snapshot_Metadata {path}: fetched_at {stamp!r} is not a real UTC time") from None
    if not _is_sha256(digest):
        raise LabelError(
            who, f"Snapshot_Metadata {path}: sha256 {digest!r} is not 64 lowercase hexadecimal characters")
    return SnapshotMetadata(request_url=url, fetched_at=fetched_at, sha256=digest)


def check_response(entry: ManifestEntry, body: bytes) -> dict:
    """Fetch-time checks on an HTTP-200 openFDA body (Requirement 7.5). Returns the single label.

    Raises LabelError naming the entry's drug and the failed check.
    """
    drug = entry.generic_name

    def fail(check: str) -> LabelError:
        return LabelError(drug, check)

    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise fail(f"response body is not valid JSON: {exc}") from None

    meta = document.get("meta") if isinstance(document, dict) else None
    results_meta = meta.get("results") if isinstance(meta, dict) else None
    total = results_meta.get("total") if isinstance(
        results_meta, dict) else None
    if type(total) is not int or total != 1:
        raise fail(f"meta.results.total is {total!r}, expected 1")

    results = document.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        count = len(results) if isinstance(results, list) else None
        raise fail(
            f"results must hold exactly one label object, found {count!r} elements")
    label = results[0]

    if "set_id" not in label:
        raise fail("the label has no set_id")
    if label["set_id"] != entry.set_id:
        raise fail(
            f"set_id {label['set_id']!r} does not equal the pinned set id {entry.set_id!r}")

    openfda = label.get("openfda")
    names = openfda.get("generic_name") if isinstance(openfda, dict) else None
    wanted = drug.casefold()
    if not isinstance(names, list) or not any(isinstance(n, str) and wanted in n.casefold() for n in names):
        raise fail(
            f"no openfda.generic_name element contains {drug!r} (found {names!r})")
    return label


def content_hash(text: str, *, drug: str | None = None, field: str | None = None) -> str:
    """Content_Hash: lowercase hex SHA-256 of the UTF-8 bytes, as `evidence_check/verify.py` computes it."""
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LabelError(drug or "unknown drug",
                         f"{field or 'text'} cannot be encoded as UTF-8: {exc}") from None
    return hashlib.sha256(data).hexdigest()


def load_label(entry: ManifestEntry, label_dir: Path) -> LoadedLabel:
    """Seed-time checks on one committed Label_Snapshot (Requirements 8.1, 8.2, 8.7).

    Reads only `<slug>.json` and `<slug>.meta.json` for `entry` from `label_dir`. Raises LabelError naming the
    drug and the first failed check, in this order: snapshot present, metadata present, SHA-256 of the
    snapshot bytes equals the metadata, JSON parses, exactly one result, `set_id` present, `set_id` equals
    the pin, `effective_time` is 8 digits forming a calendar date. Opens no network or database connection.
    """
    drug = entry.generic_name
    stem = slug(drug)
    snapshot_path = Path(label_dir) / f"{stem}.json"
    meta_path = Path(label_dir) / f"{stem}.meta.json"

    def fail(check: str) -> LabelError:
        return LabelError(drug, check)

    try:
        raw = snapshot_path.read_bytes()
    except FileNotFoundError:
        raise fail(
            f"Label_Snapshot file {snapshot_path} is missing; run {FETCH_COMMAND}") from None
    metadata = read_metadata(meta_path, drug=drug)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != metadata.sha256:
        raise fail(
            f"SHA-256 of {snapshot_path} is {digest}, but its Snapshot_Metadata records {metadata.sha256}; "
            f"run {FETCH_COMMAND}"
        )

    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise fail(
            f"Label_Snapshot {snapshot_path} is not valid JSON: {exc}") from None

    results = document.get("results") if isinstance(document, dict) else None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        count = len(results) if isinstance(results, list) else None
        raise fail(
            f"results must hold exactly one label object, found {count!r} elements")
    label = results[0]

    if "set_id" not in label:
        raise fail("the label has no set_id")
    if label["set_id"] != entry.set_id:
        raise fail(
            f"set_id {label['set_id']!r} does not equal the pinned set id {entry.set_id!r}")

    effective_time = label.get("effective_time")
    if not isinstance(effective_time, str) or re.match(_EFFECTIVE_TIME_RE, effective_time) is None:
        raise fail(
            f"effective_time {effective_time!r} is not exactly 8 digits (YYYYMMDD)")
    try:
        datetime.strptime(effective_time, "%Y%m%d")
    except ValueError:
        raise fail(
            f"effective_time {effective_time!r} is not a valid calendar date in YYYYMMDD form") from None

    return LoadedLabel(entry=entry, label=label, metadata=metadata)


def import_sections(loaded: LoadedLabel) -> tuple[list[SectionRow], list[str]]:
    """Turn one checked label into DRUG_LABEL_SECTION rows (Requirements 8.3, 8.4, 8.5, 8.8, 8.9, 8.13).

    Walks IMPORTED_FIELDS in order and each field's elements in snapshot order. Every string of one or more
    characters becomes a row with its exact text and SECTION_ID = 1000 * position + 100 * f + e, where f is
    the 1-based field index and e the 0-based element index. Returns the rows and the operator notices
    (one per skipped empty element, and one when no row was produced). Raises LabelError for an element
    index of 100 or more, a field that is not a list of strings, or text that cannot be encoded as UTF-8.
    """
    drug = loaded.entry.generic_name
    position = loaded.entry.position
    rows: list[SectionRow] = []
    notices: list[str] = []
    for field_index, field in enumerate(IMPORTED_FIELDS, start=1):
        if field not in loaded.label:
            continue
        elements = loaded.label[field]
        if not isinstance(elements, list):
            raise LabelError(
                drug, f"{field} is {type(elements).__name__}, expected a list of strings")
        for element, text in enumerate(elements):
            if element >= _MAX_ELEMENTS:
                raise LabelError(
                    drug, f"{field} has {len(elements)} elements; at most {_MAX_ELEMENTS} fit the SECTION_ID scheme"
                )
            if not isinstance(text, str):
                raise LabelError(
                    drug, f"{field}[{element}] is {type(text).__name__}, expected a string")
            if text == "":
                notices.append(f"{drug}: empty {field} element skipped")
                continue
            rows.append(
                SectionRow(
                    section_id=1000 * position + 100 * field_index + element,
                    generic_name=drug,
                    section_type=field,
                    element=element,
                    text=text,
                    content_sha256=content_hash(
                        text, drug=drug, field=f"{field}[{element}]"),
                )
            )
    if not rows:
        notices.append(f"no label sections were imported for {drug}")
    return rows, notices
