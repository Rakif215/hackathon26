"""Schema_Apply (`--apply-schema`) against an in-memory fake Exasol connection (offline: no network, no database).

Reuses the Default_Seed_Run fakes of `test_seed_run.py` and adds the statements Schema_Apply sends: the
system-table reads for the inventory and DDL. DDL on the fake takes effect at once, as it does on an
autocommit connection, so a test sees exactly what a failed run leaves applied. The fake starts from a
legacy MEDGUARD: the four legacy-only tables, PATIENT and AUDIT_LOG in their legacy layouts, a few canonical
tables with rows, two canonical tables missing, and one unmanaged table.
Requirements 2.1-2.9, 15.2, 15.3, 16.3.
"""
from __future__ import annotations

import copy
import dataclasses
import io
import re
from datetime import date

import pytest
from test_seed_run import (
    DDL_RE,
    FORMATTER,
    SENTINEL,
    TARGET,
    FakeConnection,
    FakeDb,
    FakeEvidence,
    Result,
    expected_writes,
    found_rows,
)

from hackathon26 import seed
from hackathon26.demo_fixture import SEED_OWNED_TABLES
from hackathon26.schema_file import compare_columns, parse_tables, split_statements

LEGACY_ONLY = ("DRUG_PRODUCT", "PRESCRIPTION", "DISPENSING", "REVIEW_QUEUE")
VERSION = "2026.2.0"
SCHEMA_DDL_RE = re.compile(
    rf"{DDL_RE.pattern}|^\s*OPEN\s+SCHEMA\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def inputs() -> seed.ValidatedInputs:
    validated, problems = seed.validate_offline()
    assert problems == [] and validated is not None
    return validated


def _live_type(type_text: str) -> str:
    """How SYS.EXA_ALL_COLUMNS reports a Schema_File type: character types carry a character set."""
    return f"{type_text} UTF8" if type_text.startswith(("VARCHAR", "CHAR")) else type_text


class ApplyConnection(FakeConnection):
    def __init__(self, db: "ApplyDb", number: int, autocommit) -> None:
        super().__init__(db, number)
        self.autocommit = autocommit
        self.open_schema: str | None = None

    def execute(self, query, query_params=None):
        sql = (query if query_params is None else FORMATTER.format(
            query, **query_params)).strip().rstrip(";")
        db = self.db
        if SCHEMA_DDL_RE.match(sql):
            return self._ddl(sql)
        if re.search(r"\bFROM SYS\.EXA_METADATA\b", sql):
            db.log.append(("sql", self.number, sql))
            return Result([(db.version,)])
        if re.search(r"\bFROM SYS\.EXA_ALL_TABLES\b", sql):
            db.log.append(("sql", self.number, sql))
            return Result([(table,) for table in db.columns] if db.schema_exists else [])
        return super().execute(query, query_params)

    def _ddl(self, sql: str) -> Result:
        db = self.db
        db.log.append(("sql", self.number, sql))
        if db.output_at_first_ddl is None:
            db.output_at_first_ddl = db.out.getvalue()
        if not self.autocommit:
            db.unexpected.append(sql)
            raise RuntimeError("DDL on a connection without autocommit")
        if db.fail_ddl is not None and sql.startswith(db.fail_ddl):
            raise RuntimeError(
                f"[{sql[:30]}] object is locked by another session (sys/{SENTINEL})")
        if m := re.fullmatch(r"DROP TABLE IF EXISTS MEDGUARD\.(\w+)", sql):
            if m[1] not in db.ignore_drop:
                for store in (db.columns, db.committed, self.work):
                    store.pop(m[1], None)
            return Result([])
        if sql == "CREATE SCHEMA IF NOT EXISTS MEDGUARD":
            db.schema_exists = True
            return Result([])
        if sql == "OPEN SCHEMA MEDGUARD":
            self.open_schema = "MEDGUARD"
            return Result([])
        if re.match(r"CREATE OR REPLACE TABLE \w+\b", sql) and self.open_schema == "MEDGUARD":
            (name, columns), = parse_tables(sql).items()
            db.columns[name] = {c.name: db.type_override.get((name, c.name), _live_type(c.type_text))
                                for c in columns}
            rows = db.committed.get(name, []) if name in db.keep_rows else []
            db.committed[name] = copy.deepcopy(rows)
            self.work[name] = copy.deepcopy(rows)
            return Result([])
        db.unexpected.append(sql)
        raise RuntimeError(f"unexpected DDL: {sql[:80]}")


class ApplyDb(FakeDb):
    """A fake MEDGUARD in the legacy state Schema_Apply is written for."""

    def __init__(self, inputs: seed.ValidatedInputs, out: io.StringIO) -> None:
        super().__init__(inputs)
        self.out = out
        self.version = VERSION
        self.output_at_first_ddl: str | None = None
        self.fail_ddl: str | None = None  # a statement prefix that fails
        self.ignore_drop: set[str] = set()
        self.keep_rows: set[str] = set()
        self.type_override: dict[tuple[str, str], str] = {}
        for table in ("RISK_RULE_CLASS", "DRUG_MENTION"):
            del self.columns[table], self.committed[table]
        self.columns["PATIENT"] = {"PATIENT_ID": "DECIMAL(18,0)", "DISPLAY_NAME": "VARCHAR(200) UTF8",
                                   "LANGUAGE": "VARCHAR(10) UTF8"}
        self.committed["PATIENT"] = [{"PATIENT_ID": 1}, {"PATIENT_ID": 2}]
        self.columns["AUDIT_LOG"] = {"EVENT_ID": "DECIMAL(18,0)", "ACTOR": "VARCHAR(100) UTF8",
                                     "EVENT_ACTION": "VARCHAR(100) UTF8"}
        for count, table in enumerate(LEGACY_ONLY):
            self.columns[table] = {"ID": "DECIMAL(18,0)"}
            self.committed[table] = [{"ID": i} for i in range(count)]
        self.columns["TEAM_NOTES"] = {"NOTE": "VARCHAR(100) UTF8"}
        self.committed["TEAM_NOTES"] = [{"NOTE": "ours"}, {"NOTE": "keep"}]
        self.before = copy.deepcopy(self.committed)
        self.columns_before = copy.deepcopy(self.columns)

    def __call__(self, **kwargs) -> ApplyConnection:
        self.calls.append(kwargs)
        if self.connect_error is not None:
            raise self.connect_error
        return ApplyConnection(self, len(self.calls), kwargs.get("autocommit"))

    def ddl(self) -> list[tuple[int, str]]:
        return [(entry[1], entry[2]) for entry in self.log if entry[0] == "sql" and SCHEMA_DDL_RE.match(entry[2])]


def setup(inputs):
    out, err = io.StringIO(), io.StringIO()
    return ApplyDb(inputs, out), out, err


def run_main(inputs, db: ApplyDb, out, err, argv=("--apply-schema",)):
    evidence = FakeEvidence(db, found_rows(inputs))
    code = seed.main(list(argv), connect_factory=db, out=out,
                     err=err, target=TARGET, evidence_source=evidence)
    assert SENTINEL not in out.getvalue() + err.getvalue(), "a credential value was printed"
    assert db.unexpected == []
    return code, out.getvalue(), err.getvalue(), evidence


def apply(inputs, db: ApplyDb, out, err, *, target=TARGET):
    code = seed.schema_apply(inputs, connect_factory=db,
                             out=out, err=err, target=target)
    assert SENTINEL not in out.getvalue() + err.getvalue(), "a credential value was printed"
    assert db.unexpected == []
    return code, out.getvalue(), err.getvalue()


LEGACY_MARKED = sorted((*LEGACY_ONLY, "PATIENT", "AUDIT_LOG"))


def expected_ddl(inputs, dropped=LEGACY_MARKED) -> list[str]:
    return [f"DROP TABLE IF EXISTS MEDGUARD.{table}" for table in dropped] + split_statements(inputs.schema_sql)


# --- Connection (Requirements 2.8, 16.3) ---


def test_schema_apply_uses_autocommit_and_the_seed_then_uses_a_transaction(inputs):
    db, out, err = setup(inputs)
    code, out_text, err_text, _ = run_main(inputs, db, out, err)
    assert code == seed.EXIT_OK, err_text
    assert db.calls[0] == {"schema": "",
                           "autocommit": True, "connection_timeout": 30}
    assert db.calls[1] == {"schema": "",
                           "autocommit": False, "connection_timeout": 30}
    assert {number for number, _ in db.ddl()} == {1}


def test_connect_error_exits_4_with_host_port_and_redacted_error(inputs):
    db, out, err = setup(inputs)
    db.connect_error = RuntimeError(
        f"login failed for sys with password {SENTINEL}")
    code, out_text, err_text = apply(inputs, db, out, err)
    assert code == seed.EXIT_CONNECT
    assert "db.example.test:8563" in err_text and "login failed" in err_text and "***" in err_text
    assert db.log == []


# --- Inventory before any DDL (Requirements 2.2, 2.3, 2.6) ---


def test_target_and_every_live_table_with_count_and_mark_are_printed_before_any_ddl(inputs):
    db, out, err = setup(inputs)
    code, _, err_text = apply(inputs, db, out, err)
    assert code == seed.EXIT_OK, err_text
    before = db.output_at_first_ddl
    assert before is not None
    for text in ("db.example.test", "8563", VERSION, "MEDGUARD"):
        assert text in before
    marks = {table: "to be dropped" for table in LEGACY_MARKED}
    marks |= {table: "to be replaced empty" for table in db.columns_before
              if table in inputs.tables and table not in marks}
    marks["TEAM_NOTES"] = "unmanaged, left unchanged"
    assert set(marks) == set(db.columns_before)
    lines = before.splitlines()
    for table, mark in marks.items():
        line = next((line for line in lines if re.search(
            rf"\bMEDGUARD\.{table}\b", line)), None)
        assert line is not None, (table, before)
        assert re.search(rf"\b{len(db.before[table])} rows?\b", line), line
        assert mark in line, line
    assert "SELECT COUNT(*) FROM MEDGUARD.TEAM_NOTES" in db.sql()


# --- Drops, Schema_File order, unmanaged tables (Requirements 2.4, 2.6, 15.2, 16.3) ---


def test_legacy_tables_are_dropped_qualified_then_the_schema_file_runs_in_file_order(inputs):
    db, out, err = setup(inputs)
    code, _, err_text = apply(inputs, db, out, err)
    assert code == seed.EXIT_OK, err_text
    ddl = [sql for _, sql in db.ddl()]
    assert ddl == expected_ddl(inputs)
    file_statements = set(split_statements(inputs.schema_sql))
    assert all(
        sql in file_statements for sql in ddl if sql.upper().startswith("CREATE"))
    assert split_statements(inputs.schema_sql)[:2] == ["CREATE SCHEMA IF NOT EXISTS MEDGUARD",
                                                       "OPEN SCHEMA MEDGUARD"]


def test_unmanaged_tables_and_their_rows_are_left_unchanged(inputs):
    db, out, err = setup(inputs)
    code, _, _, _ = run_main(inputs, db, out, err)
    assert code == seed.EXIT_OK
    assert db.columns["TEAM_NOTES"] == db.columns_before["TEAM_NOTES"]
    assert db.committed["TEAM_NOTES"] == db.before["TEAM_NOTES"]
    assert [sql for sql in db.sql() if "TEAM_NOTES" in sql] == [
        "SELECT COUNT(*) FROM MEDGUARD.TEAM_NOTES"]


# --- Failure (Requirement 2.8) ---


@pytest.mark.parametrize("prefix, shown", [
    ("DROP TABLE IF EXISTS MEDGUARD.PRESCRIPTION", "MEDGUARD.PRESCRIPTION"),
    ("CREATE OR REPLACE TABLE LAB_RESULT", "MEDGUARD.LAB_RESULT"),
    ("OPEN SCHEMA MEDGUARD", "OPEN SCHEMA MEDGUARD"),
])
def test_first_failing_statement_stops_the_run_and_skips_the_seed(inputs, prefix, shown):
    db, out, err = setup(inputs)
    db.fail_ddl = prefix
    code, out_text, err_text, evidence = run_main(inputs, db, out, err)
    assert code == seed.EXIT_SCHEMA_APPLY == 6
    assert shown in err_text
    assert "object is locked" in err_text and "***" in err_text
    assert "Statements executed before this failure stay applied" in err_text
    assert db.sql()[-1].startswith(prefix)  # no further statement of any kind
    assert len(db.calls) == 1 and evidence.calls == [] and db.writes() == []


def test_statements_before_the_failure_stay_applied_and_a_rerun_completes(inputs):
    db, out, err = setup(inputs)
    db.fail_ddl = "CREATE OR REPLACE TABLE LAB_RESULT"
    code, _, _ = apply(inputs, db, out, err)
    assert code == seed.EXIT_SCHEMA_APPLY
    assert not set(LEGACY_ONLY) & set(db.columns)
    assert db.columns["DRUG"] == {c.name: _live_type(
        c.type_text) for c in inputs.tables["DRUG"]}
    assert "LANGUAGE" not in db.columns["PATIENT"]

    db.fail_ddl = None
    rerun_out, rerun_err = io.StringIO(), io.StringIO()
    db.out = rerun_out
    code, out_text, err_text, evidence = run_main(
        inputs, db, rerun_out, rerun_err)
    assert code == seed.EXIT_OK, err_text
    assert compare_columns(inputs.tables, db.columns, compare_types=True) == []
    assert not set(LEGACY_ONLY) & set(db.columns)
    assert db.committed["TEAM_NOTES"] == db.before["TEAM_NOTES"]
    assert evidence.calls == [(1, date(2026, 11, 13), 104, None)]


# --- Post-check (Requirement 2.5) ---


def test_post_check_reads_columns_tables_and_app_written_counts_after_the_last_statement(inputs):
    db, out, err = setup(inputs)
    code, out_text, err_text = apply(inputs, db, out, err)
    assert code == seed.EXIT_OK, err_text
    sql = db.sql()
    last_ddl = max(i for i, text in enumerate(sql)
                   if SCHEMA_DDL_RE.match(text))
    after = sql[last_ddl + 1:]
    assert any("SYS.EXA_ALL_COLUMNS" in text for text in after)
    assert any("SYS.EXA_ALL_TABLES" in text for text in after)
    for table in set(inputs.tables) - set(SEED_OWNED_TABLES):
        assert f"SELECT COUNT(*) FROM MEDGUARD.{table}" in after
    assert compare_columns(inputs.tables, db.columns, compare_types=True) == []
    assert all(db.committed[table] == [] for table in inputs.tables)


@pytest.mark.parametrize("tamper, expected", [
    ("type", ("MEDGUARD.DRUG", "RXCUI", "VARCHAR", "DECIMAL")),
    ("legacy", ("MEDGUARD.REVIEW_QUEUE",)),
    ("rows", ("MEDGUARD.CLINICIAN_REVIEW", "1 row")),
])
def test_failed_post_check_exits_6_and_skips_the_seed(inputs, tamper, expected):
    db, out, err = setup(inputs)
    if tamper == "type":
        db.type_override[("DRUG", "RXCUI")] = "DECIMAL(18,0)"
    elif tamper == "legacy":
        db.ignore_drop.add("REVIEW_QUEUE")
    else:
        db.keep_rows.add("CLINICIAN_REVIEW")
    code, out_text, err_text, evidence = run_main(inputs, db, out, err)
    assert code == seed.EXIT_SCHEMA_APPLY
    for text in expected:
        assert text in err_text, (text, err_text)
    assert len(db.calls) == 1 and evidence.calls == [] and db.writes() == []


# --- Continuation into the Default_Seed_Run (Requirement 2.7) ---


def test_successful_apply_continues_into_the_default_seed_run(inputs):
    db, out, err = setup(inputs)
    code, out_text, err_text, evidence = run_main(inputs, db, out, err)
    assert code == seed.EXIT_OK, err_text
    assert db.writes() == expected_writes(inputs)
    for table in set(inputs.tables) - set(SEED_OWNED_TABLES):
        assert db.committed[table] == []
    assert evidence.calls == [(1, date(2026, 11, 13), 104, None)]
    assert "EVIDENCE_FOUND" in out_text


# --- No DDL without the option (Requirements 2.1, 15.3) ---


def test_no_ddl_runs_without_the_option(inputs):
    db, out, err = setup(inputs)
    code, _, err_text, _ = run_main(inputs, db, out, err, argv=())
    assert code == seed.EXIT_COLUMNS
    assert db.ddl() == []
    assert db.columns == db.columns_before and db.committed == db.before

    canonical = FakeDb(inputs)
    run_out, run_err = io.StringIO(), io.StringIO()
    code = seed.main([], connect_factory=canonical, out=run_out, err=run_err, target=TARGET,
                     evidence_source=FakeEvidence(canonical, found_rows(inputs)))
    assert code == seed.EXIT_OK, run_err.getvalue()
    assert not any(SCHEMA_DDL_RE.match(sql) for sql in canonical.sql())


def test_schema_file_that_does_not_open_medguard_first_is_refused_before_connecting(inputs):
    statements = split_statements(inputs.schema_sql)
    other = ";\n".join(["CREATE SCHEMA IF NOT EXISTS OTHER",
                       "OPEN SCHEMA OTHER", *statements[2:]]) + ";\n"
    db, out, err = setup(inputs)
    code, _, err_text = apply(dataclasses.replace(
        inputs, schema_sql=other), db, out, err)
    assert code == seed.EXIT_SCHEMA_APPLY
    assert "OPEN SCHEMA MEDGUARD" in err_text
    assert db.calls == [] and db.log == []
