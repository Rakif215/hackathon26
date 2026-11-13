"""Default_Seed_Run against an in-memory fake Exasol connection (offline: no network, no database).

The fake keeps a committed copy and a per-connection working copy of every table, so a test can see what a
ROLLBACK or COMMIT left behind. SQL is formatted with pyexasol's own `ExaFormatter`, so the recorded text is
what the server would receive. Credentials, the target host and the evidence source are injected:
`db.settings()` is never called.
Requirements 3.1-3.3, 3.6-3.9, 3.11, 8.10, 8.12, 13.8, 13.9, 13.11, 15.3, 16.1-16.3, 16.5, 16.6.
"""
from __future__ import annotations

import copy
import io
import re
from datetime import date
from types import SimpleNamespace

import pytest
from pyexasol import ExaFormatter

from hackathon26 import seed
from hackathon26.demo_fixture import SEED_OWNED_TABLES
from hackathon26.evidence_check.models import EvidenceRow
from hackathon26.evidence_check.repository import EvidenceStoreUnavailable
from hackathon26.resolution.repository import UnknownPatient

SENTINEL = "s3ntinel-Pa55w0rd"
TARGET = seed.ConnectionTarget("db.example.test", 8563, SENTINEL)
NLS_OK = {
    "NLS_DATE_FORMAT": "YYYY-MM-DD",
    "NLS_TIMESTAMP_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF6",
    "NLS_NUMERIC_CHARACTERS": ".,",
}
FORMATTER = ExaFormatter(SimpleNamespace(options={"quote_ident": False}))
DDL_RE = re.compile(r"^\s*(CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE)\b", re.IGNORECASE)
WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|MERGE)\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def inputs() -> seed.ValidatedInputs:
    validated, problems = seed.validate_offline()
    assert problems == [] and validated is not None
    return validated


class Result:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return list(self._rows)

    def fetchval(self):
        return self._rows[0][0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeConnection:
    """One session: reads and writes a working copy that COMMIT publishes and ROLLBACK discards."""

    def __init__(self, db: "FakeDb", number: int) -> None:
        self.db, self.number = db, number
        self.work = copy.deepcopy(db.committed)
        self.ext = SimpleNamespace(insert_multi=self._insert_multi)

    def _fail(self, kind: str, table: str) -> None:
        if self.db.fail_on == (kind, table):
            raise RuntimeError(f"[{kind} {table}] constraint violation (connected as sys/{SENTINEL})")

    def execute(self, query, query_params=None):
        sql = query if query_params is None else FORMATTER.format(query, **query_params)
        sql = sql.strip().rstrip(";")
        self.db.log.append(("sql", self.number, sql))
        if m := re.fullmatch(r"DELETE FROM MEDGUARD\.(\w+)", sql):
            self._fail("delete", m[1])
            self.work[m[1]] = []
            return Result([])
        if re.search(r"\bFROM SYS\.EXA_SCHEMAS\b", sql):
            return Result([("MEDGUARD",)] if self.db.schema_exists else [])
        if re.search(r"\bFROM SYS\.EXA_ALL_COLUMNS\b", sql):
            if not self.db.schema_exists:
                return Result([])
            return Result([(t, c, ty) for t, cols in self.db.columns.items() for c, ty in cols.items()])
        if re.search(r"\bFROM SYS\.EXA_PARAMETERS\b", sql):
            return Result(list(self.db.nls.items()))
        if m := re.fullmatch(r"SELECT COUNT\(\*\) FROM MEDGUARD\.(\w+)", sql):
            return Result([(len(self.work.get(m[1], [])),)])
        if re.search(r"SELECT SECTION_ID, SECTION_TEXT, CONTENT_SHA256\s+FROM MEDGUARD\.DRUG_LABEL_SECTION", sql):
            rows = sorted((r["SECTION_ID"], r["SECTION_TEXT"], r["CONTENT_SHA256"])
                          for r in self.work["DRUG_LABEL_SECTION"])
            return Result(self.db.read_back(rows) if self.db.read_back else rows)
        self.db.unexpected.append(sql)
        raise RuntimeError(f"unexpected SQL for sys/{SENTINEL}: {sql[:120]}")

    def _insert_multi(self, table_name, data, columns=None):
        data = list(data)
        self.db.log.append(("insert", self.number, table_name, data, list(columns or ())))
        schema, table = table_name
        self._fail("insert", table)
        self.work[table].extend(dict(zip(columns, row, strict=True)) for row in data)

    def commit(self) -> None:
        self.db.log.append(("commit", self.number))
        if self.db.commit_error is not None:
            raise self.db.commit_error
        self.db.committed = copy.deepcopy(self.work)

    def rollback(self) -> None:
        self.db.log.append(("rollback", self.number))
        self.work = copy.deepcopy(self.db.committed)

    def close(self) -> None:
        self.db.log.append(("close", self.number))

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class FakeDb:
    """A `connect_factory` over a fake MEDGUARD schema whose columns match the Schema_File."""

    def __init__(self, inputs: seed.ValidatedInputs) -> None:
        self.schema_exists = True
        self.columns = {t: {c.name: c.type_text for c in cols} for t, cols in inputs.tables.items()}
        self.nls = dict(NLS_OK)
        self.committed: dict[str, list[dict]] = {t: [] for t in inputs.tables}
        # Rows a run must never touch (App_Written_Tables) or must replace (a hand-added seed row).
        self.committed["AUDIT_LOG"] = [{"AUDIT_ID": 1, "NOTE": "written by the API"}]
        self.committed["CLINICIAN_REVIEW"] = [{"REVIEW_ID": 7}]
        self.committed["DRUG"] = [{"DRUG_ID": 999, "GENERIC_NAME": "added by hand"}]
        self.before = copy.deepcopy(self.committed)
        self.calls: list[dict] = []
        self.log: list[tuple] = []
        self.unexpected: list[str] = []
        self.connect_error: Exception | None = None
        self.fail_on: tuple[str, str] | None = None
        self.read_back = None
        self.commit_error: Exception | None = None

    def __call__(self, **kwargs) -> FakeConnection:
        self.calls.append(kwargs)
        if self.connect_error is not None:
            raise self.connect_error
        return FakeConnection(self, len(self.calls))

    def sql(self) -> list[str]:
        return [entry[2] for entry in self.log if entry[0] == "sql"]

    def writes(self) -> list[tuple]:
        """Every write in order: ("delete", table) or ("insert", table_name, rows, columns)."""
        found = []
        for entry in self.log:
            if entry[0] == "sql" and WRITE_RE.match(entry[2]):
                m = re.fullmatch(r"DELETE FROM MEDGUARD\.(\w+)", entry[2])
                found.append(("delete", m[1]) if m else ("other", entry[2]))
            elif entry[0] == "insert":
                found.append(("insert", entry[2], entry[3], entry[4]))
        return found

    def kinds(self) -> list[str]:
        return [entry[0] for entry in self.log]


class FakeEvidence:
    """An `EvidenceSource` returning prepared rows or raising, recording each call and the log at that time."""

    def __init__(self, db: FakeDb, rows=None, error: Exception | None = None) -> None:
        self.db, self.rows, self.error = db, rows or [], error
        self.calls: list[tuple] = []
        self.log_at_call: list[tuple] = []

    def fetch(self, patient_id, request):
        self.calls.append((patient_id, request.as_of, request.candidate_drug_id, request.candidate_class_name))
        self.log_at_call = list(self.db.log)
        if self.error is not None:
            raise self.error
        return self.rows


def found_rows(inputs: seed.ValidatedInputs) -> list[EvidenceRow]:
    """One verifiable Evidence_Join_Query row built from the seeded rule 401 and its label section."""
    sections = {row["SECTION_ID"]: row for row in inputs.rows["DRUG_LABEL_SECTION"]}
    rule = inputs.rows["RISK_LAB_RULE"][0]
    section = sections[rule["EVIDENCE_SECTION_ID"]]
    return [EvidenceRow(
        rule_id=rule["RULE_ID"], rule_name=rule["RULE_NAME"], analyte=rule["ANALYTE"],
        direction=rule["DIRECTION"], supplying_medications="furosemide, ramipril",
        section_id=section["SECTION_ID"], section_type=section["SECTION_TYPE"],
        label_set_id=section["LABEL_SET_ID"], label_effective_at=section["LABEL_EFFECTIVE_AT"],
        source_url=section["SOURCE_URL"], content_sha256=section["CONTENT_SHA256"],
        section_text=section["SECTION_TEXT"], evidence_quote=rule["EVIDENCE_QUOTE"],
        lab_id=None, value_num=None, unit=None, ref_low=None, ref_high=None, measured_at=None,
    )]


def run_seed(inputs, db: FakeDb, *, evidence=None, use_default_evidence=False, allow_unexpected=False):
    out, err = io.StringIO(), io.StringIO()
    if evidence is None and not use_default_evidence:
        evidence = FakeEvidence(db, found_rows(inputs))
    code = seed.default_seed_run(inputs, connect_factory=db, out=out, err=err, target=TARGET,
                                 evidence_source=evidence)
    text = out.getvalue() + err.getvalue()
    assert SENTINEL not in text, "a credential value was printed"
    assert not any(DDL_RE.match(sql) for sql in db.sql()), "the Default_Seed_Run executed DDL"
    if not allow_unexpected:
        assert db.unexpected == []
    return code, out.getvalue(), err.getvalue(), evidence


def expected_writes(inputs) -> list[tuple]:
    writes = []
    for table in SEED_OWNED_TABLES:
        columns = [column.name for column in inputs.tables[table]]
        writes += [("delete", table), ("insert", ("MEDGUARD", table), inputs.wire_rows[table], columns)]
    return writes


# --- Connection (Requirements 3.11, 16.1, 16.3, 16.6) ---


def test_seed_connection_uses_empty_schema_autocommit_off_and_30_second_timeout(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    assert db.calls[0] == {"schema": "", "autocommit": False, "connection_timeout": 30}


def test_connect_error_exits_4_with_host_port_and_redacted_error(inputs):
    db = FakeDb(inputs)
    db.connect_error = RuntimeError(f"login failed for user sys with password {SENTINEL}")
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_CONNECT
    assert "db.example.test:8563" in err
    assert "login failed" in err and "***" in err
    assert db.log == [] and evidence.calls == []
    assert db.committed == db.before


# --- Column check (Requirements 3.1, 3.2) ---


def test_column_mismatch_exits_5_naming_table_columns_and_apply_schema_and_writes_nothing(inputs):
    db = FakeDb(inputs)
    del db.columns["DRUG"]["RXCUI"]
    db.columns["DRUG"]["LEGACY_NOTE"] = "VARCHAR(100) UTF8"
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_COLUMNS
    line = next(line for line in err.splitlines() if "DRUG" in line and "RXCUI" in line)
    assert "LEGACY_NOTE" in line
    assert "--apply-schema" in err
    assert db.writes() == [] and "commit" not in db.kinds()
    assert db.committed == db.before and evidence.calls == []


def test_missing_table_and_missing_schema_exit_5(inputs):
    db = FakeDb(inputs)
    del db.columns["RISK_RULE_CLASS"]
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_COLUMNS
    assert "RISK_RULE_CLASS" in err and "--apply-schema" in err and db.writes() == []

    db = FakeDb(inputs)
    db.schema_exists = False
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_COLUMNS
    assert "MEDGUARD" in err and "--apply-schema" in err and db.writes() == []


def test_column_order_and_unmanaged_tables_do_not_affect_the_check(inputs):
    db = FakeDb(inputs)
    db.columns["DRUG"] = dict(reversed(list(db.columns["DRUG"].items())))
    db.columns["TEAM_NOTES"] = {"NOTE": "VARCHAR(10) UTF8"}
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    assert all("TEAM_NOTES" not in write[1] for write in db.writes())


def test_checks_read_only_medguard_and_system_tables_before_any_write(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    sql = db.sql()
    first_write = next(i for i, text in enumerate(sql) if WRITE_RE.match(text))
    before = sql[:first_write]
    assert any("SYS.EXA_SCHEMAS" in text for text in before)
    assert any("SYS.EXA_ALL_COLUMNS" in text for text in before)
    assert any("SYS.EXA_PARAMETERS" in text for text in before)
    for text in sql:
        names = re.findall(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([\w.]+)", text, re.IGNORECASE)
        assert all(name.startswith(("MEDGUARD.", "SYS.")) for name in names), text


# --- Session format check (Requirement 3.9, 15.3) ---


@pytest.mark.parametrize("parameter, value", [
    ("NLS_DATE_FORMAT", "DD.MM.YYYY"),
    ("NLS_TIMESTAMP_FORMAT", "YYYY-MM-DD HH24:MI:SS.FF3"),
    ("NLS_NUMERIC_CHARACTERS", ",."),
    ("NLS_DATE_FORMAT", None),
])
def test_nls_format_mismatch_exits_7_writes_nothing_and_never_alters_the_session(inputs, parameter, value):
    db = FakeDb(inputs)
    if value is None:
        del db.nls[parameter]
    else:
        db.nls[parameter] = value
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_WRITE
    assert parameter in err
    assert db.writes() == [] and "commit" not in db.kinds()
    assert not any(re.search(r"\bALTER\b", text, re.IGNORECASE) for text in db.sql())
    assert db.committed == db.before and evidence.calls == []


# --- Writes (Requirements 3.3, 3.6, 16.3) ---


def test_each_seed_owned_table_is_deleted_then_inserted_in_fixed_order(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    assert db.writes() == expected_writes(inputs)
    kinds = db.kinds()
    assert kinds.count("commit") == 1
    assert kinds.index("commit") > max(i for i, kind in enumerate(kinds) if kind == "insert")
    for table in SEED_OWNED_TABLES:
        columns = [column.name for column in inputs.tables[table]]
        assert db.committed[table] == [dict(zip(columns, row)) for row in inputs.wire_rows[table]]


def test_app_written_tables_are_never_written(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    app_written = set(inputs.tables) - set(SEED_OWNED_TABLES)
    assert {"CLINICIAN_REVIEW", "AUDIT_LOG"} <= app_written
    touched = {write[1] if write[0] == "delete" else write[1][1] for write in db.writes()}
    assert touched == set(SEED_OWNED_TABLES)
    for table in app_written:
        assert db.committed[table] == db.before[table]


# --- Storage round trip (Requirements 8.10, 8.12, 3.7) ---


def _first_section(inputs) -> dict:
    return min(inputs.rows["DRUG_LABEL_SECTION"], key=lambda row: row["SECTION_ID"])


def _drug_name(inputs, drug_id: int) -> str:
    return next(row["GENERIC_NAME"] for row in inputs.rows["DRUG"] if row["DRUG_ID"] == drug_id)


@pytest.mark.parametrize("tamper", ["missing", "changed text", "bad hash"])
def test_round_trip_mismatch_rolls_back_and_exits_7_naming_section_drug_and_type(inputs, tamper):
    section = _first_section(inputs)
    target_id = section["SECTION_ID"]

    def read_back(rows):
        if tamper == "missing":
            return [row for row in rows if row[0] != target_id]
        if tamper == "changed text":
            return [(i, text + " ", sha) if i == target_id else (i, text, sha) for i, text, sha in rows]
        return [(i, text, "0" * 64) if i == target_id else (i, text, sha) for i, text, sha in rows]

    db = FakeDb(inputs)
    db.read_back = read_back
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_WRITE
    line = next(line for line in err.splitlines() if str(target_id) in line)
    assert _drug_name(inputs, section["DRUG_ID"]) in line
    assert section["SECTION_TYPE"] in line
    kinds = db.kinds()
    assert "rollback" in kinds and "commit" not in kinds
    assert db.committed == db.before and evidence.calls == []


def test_round_trip_reads_back_by_section_id_in_the_same_transaction_before_commit(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    sql = db.sql()
    read = next(i for i, text in enumerate(sql) if "SECTION_TEXT, CONTENT_SHA256" in text)
    assert "ORDER BY SECTION_ID" in sql[read]
    entries = [entry for entry in db.log if entry[0] in ("sql", "commit")]
    read_entry = next(i for i, e in enumerate(entries) if e[0] == "sql" and "SECTION_TEXT, CONTENT_SHA256" in e[2])
    assert read_entry < next(i for i, e in enumerate(entries) if e[0] == "commit")
    assert entries[read_entry][1] == 1  # the seed connection, not a fresh one


# --- Statement errors (Requirement 3.7, 16.2, 16.6) ---


@pytest.mark.parametrize("kind, table", [("insert", "LAB_RESULT"), ("delete", "PATIENT"), ("insert", "DRUG")])
def test_statement_error_rolls_back_and_exits_7_naming_the_table(inputs, kind, table):
    db = FakeDb(inputs)
    db.fail_on = (kind, table)
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_WRITE
    assert f"MEDGUARD.{table}" in err
    assert "constraint violation" in err and "***" in err
    kinds = db.kinds()
    assert "rollback" in kinds and "commit" not in kinds
    assert db.committed == db.before and evidence.calls == []


def test_commit_error_exits_7_saying_the_outcome_is_unknown_and_a_rerun_is_safe(inputs):
    db = FakeDb(inputs)
    db.commit_error = RuntimeError(f"connection lost (sys/{SENTINEL})")
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_WRITE
    assert "COMMIT" in err and "unknown" in err and "safe" in err
    assert "connection lost" in err and "***" in err
    assert evidence.calls == []


# --- After COMMIT (Requirements 3.8, 13.8, 13.9, 13.11) ---


def test_all_17_table_counts_are_printed_after_commit(inputs):
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    assert len(inputs.tables) == 17
    for table in inputs.tables:
        expected = len(inputs.wire_rows[table]) if table in SEED_OWNED_TABLES else len(db.before[table])
        assert re.search(rf"^\s*{table}\s*:?\s+{expected}\s*$", out, re.MULTILINE), (table, out)
    entries = [entry for entry in db.log if entry[0] in ("sql", "commit")]
    commit = next(i for i, e in enumerate(entries) if e[0] == "commit")
    counts = [i for i, e in enumerate(entries) if e[0] == "sql" and e[2].startswith("SELECT COUNT(*)")]
    assert len(counts) == 17 and min(counts) > commit


def test_join_verification_runs_for_patient_1_on_2026_11_13_with_ibuprofen_104(inputs):
    db = FakeDb(inputs)
    code, out, err, evidence = run_seed(inputs, db)
    assert code == seed.EXIT_OK, err
    assert evidence.calls == [(1, date(2026, 11, 13), 104, None)]
    assert "EVIDENCE_FOUND" in out and "Clinician review required." in out
    assert ("close", 1) in evidence.log_at_call  # the seed connection is closed first


@pytest.mark.parametrize("rows, error, status", [
    ([], None, "NO_DOCUMENTED_INTERACTION_FOUND"),
    (None, UnknownPatient(), "UNKNOWN_PATIENT"),
])
def test_other_join_status_exits_8_without_rollback(inputs, rows, error, status):
    db = FakeDb(inputs)
    evidence = FakeEvidence(db, rows, error)
    code, out, err, _ = run_seed(inputs, db, evidence=evidence)
    assert code == seed.EXIT_JOIN
    assert status in out + err
    assert "rollback" not in db.kinds()
    for table in SEED_OWNED_TABLES:
        assert len(db.committed[table]) == len(inputs.wire_rows[table])


def test_query_failed_is_redacted_and_exits_8(inputs):
    db = FakeDb(inputs)
    cause = RuntimeError(f"socket closed for sys/{SENTINEL}")
    error = EvidenceStoreUnavailable("Evidence storage unavailable or incompatible")
    error.__cause__ = cause
    code, out, err, _ = run_seed(inputs, db, evidence=FakeEvidence(db, error=error))
    assert code == seed.EXIT_JOIN
    assert "QUERY_FAILED" in out + err and "socket closed" in out + err and "***" in out + err


def test_default_evidence_source_opens_a_fresh_read_connection(inputs):
    """Without an injected source the run builds EvidenceRepository over connect_factory(schema="", timeout 30)."""
    db = FakeDb(inputs)
    code, out, err, _ = run_seed(inputs, db, use_default_evidence=True, allow_unexpected=True)
    assert db.calls[1] == {"schema": "", "connection_timeout": 30}
    # The fake answers no evidence SQL, so the repository reports QUERY_FAILED, redacted.
    assert code == seed.EXIT_JOIN
    assert "QUERY_FAILED" in out + err and "***" in out + err
    assert db.unexpected and all(entry[1] == 2 for entry in db.log if entry[0] == "sql" and entry[2] in db.unexpected)
    assert "rollback" not in db.kinds()


def test_main_without_options_runs_the_default_seed_run(inputs):
    db = FakeDb(inputs)
    out, err = io.StringIO(), io.StringIO()
    code = seed.main([], connect_factory=db, out=out, err=err, target=TARGET,
                     evidence_source=FakeEvidence(db, found_rows(inputs)))
    assert code == seed.EXIT_OK, err.getvalue()
    assert db.writes() == expected_writes(inputs)
    assert SENTINEL not in out.getvalue() + err.getvalue()
