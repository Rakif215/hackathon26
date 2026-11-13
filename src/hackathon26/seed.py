"""Seed_Command: apply the canonical MEDGUARD schema and load the synthetic demo data into Exasol.

Usage (from the repo root):
    uv run python src/hackathon26/seed.py                 # Default_Seed_Run, then Join_Verification
    uv run python src/hackathon26/seed.py --apply-schema  # Schema_Apply, then Default_Seed_Run, then Join_Verification
    uv run python src/hackathon26/seed.py --verify        # Verify_Mode: Join_Verification only, writes nothing
    uv run python scripts/fetch_labels.py                 # Label_Fetcher, the only command that contacts openFDA

Schema_Apply drops the Legacy_Tables and recreates every Canonical_Table of `sql/01_schema.sql` empty,
the App_Written_Tables (CLINICIAN_REVIEW, AUDIT_LOG and the others) included. The Default_Seed_Run
replaces the rows of the Seed_Owned_Tables only. Verify_Mode writes no rows. The Label_Fetcher is the
only one of these commands that contacts openFDA; this module opens connections only to the Exasol
Target_Database that `hackathon26.db.connect` resolves. The old `--reset` option is retired: it now only
prints a message pointing to `--apply-schema` and exits with status 2.

Every input is checked offline (Demo_Fixture, Label_Manifest, Label_Snapshots, Snapshot_Metadata, rule
quotes, column lengths) before any connection is opened.

Exit status: 0 success (Join_Status EVIDENCE_FOUND); 2 usage error; 3 an input failed offline validation,
no connection opened; 4 the connection failed; 5 the live columns differ from the Schema_File; 6 a
Schema_Apply statement failed; 7 a write, read-back or session-format check failed and the run was rolled
back; 8 the rows were committed but Join_Verification did not return EVIDENCE_FOUND.

All patient data is synthetic. It describes no real person or product and must not be used clinically.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable, TextIO

if __name__ == "__main__" and not __package__:
    # `python src/hackathon26/seed.py` puts only src/hackathon26 on sys.path; the imports need src.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hackathon26.demo_fixture import (  # noqa: E402
    SEED_OWNED_TABLES,
    DemoFixture,
    FixtureError,
    SeedRows,
    build_rows,
    fixture_problems,
    load_fixture,
    to_wire,
)
from hackathon26.labels import (  # noqa: E402
    LabelError,
    LoadedLabel,
    ManifestEntry,
    content_hash,
    import_sections,
    load_label,
    load_manifest,
)
from hackathon26.schema_file import (  # noqa: E402
    CANONICAL_REPLACE,
    LEGACY_DROP,
    LEGACY_TABLE_NAMES,
    UNMANAGED,
    ColumnDef,
    classify_live_tables,
    compare_columns,
    parse_tables,
    split_statements,
)

if TYPE_CHECKING:  # importing evidence_check imports hackathon26.db; keep it out of module import
    from hackathon26.evidence_check.repository import EvidenceSource

REPO = Path(__file__).resolve().parents[2]
# Module-level so tests can point the command at temporary copies; read at call time.
FIXTURE_PATH = REPO / "data" / "demo" / "demo_fixture.json"
MANIFEST_PATH = REPO / "data" / "reference" / "label_manifest.json"
LABEL_DIR = REPO / "data" / "reference" / "labels"
SCHEMA_PATH = REPO / "sql" / "01_schema.sql"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_CONNECT = 4
EXIT_COLUMNS = 5
EXIT_SCHEMA_APPLY = 6
EXIT_WRITE = 7
EXIT_JOIN = 8

RESET_RETIRED = (
    "--reset is retired: it rebuilt the legacy six-table seed. "
    "Use --apply-schema to drop the legacy tables and recreate the canonical schema, "
    "or run without options to re-seed the existing canonical tables."
)
CANNOT_COMBINE = (
    "--apply-schema and --verify cannot be combined: --verify writes nothing, "
    "while --apply-schema rebuilds the schema. Run them as separate commands."
)

ConnectFactory = Callable[..., object]

SEED_SCHEMA = "MEDGUARD"
CONNECTION_TIMEOUT_S = 30  # Requirement 3.11
JOIN_CANDIDATE = "ibuprofen"  # Requirement 13.8: given as its DRUG_ID
# The session formats the wire values of `to_wire` are written in (design "Wire values for insert_multi").
NLS_EXPECTED = {
    "NLS_DATE_FORMAT": "YYYY-MM-DD",
    "NLS_TIMESTAMP_FORMAT": "YYYY-MM-DD HH24:MI:SS.FF6",
    "NLS_NUMERIC_CHARACTERS": ".,",
}


@dataclass(frozen=True)
class ConnectionTarget:
    """Where a run connects, for messages, and the password to redact. Only host and port are ever printed."""

    host: str
    port: int | str
    password: str | None = field(default=None, repr=False)


def _default_connect(**kwargs):
    """`hackathon26.db.connect`, imported on first use so that importing this module resolves no credentials."""
    from hackathon26.db import connect

    return connect(**kwargs)


@dataclass(frozen=True)
class ValidatedInputs:
    """Everything a run needs, built and checked offline before any connection is opened."""

    fixture: DemoFixture
    manifest: list[ManifestEntry]
    labels: list[LoadedLabel]
    schema_sql: str
    # Schema_File table -> columns in file order
    tables: dict[str, list[ColumnDef]]
    rows: SeedRows  # Seed_Owned_Table -> rows keyed by Schema_File column, in file order
    # the same rows as insert_multi tuples (to_wire values)
    wire_rows: dict[str, list[tuple]]
    # Label_Importer notices (skipped empty elements, labels without sections)
    notices: list[str]


def validate_offline() -> tuple[ValidatedInputs | None, list[str]]:
    """Load and check every committed input without opening a connection.

    Returns the validated inputs and an empty list, or None and one printable line per problem. Each line
    names the drug, the JSON path or the file and the failed check. All problems are collected, not only
    the first, so one run shows everything that needs fixing.
    """
    problems: list[str] = []

    manifest: list[ManifestEntry] | None = None
    try:
        manifest = load_manifest(MANIFEST_PATH)
    except LabelError as exc:
        problems.append(f"Label_Manifest {MANIFEST_PATH}: {exc}")

    labels: list[LoadedLabel] = []
    for entry in manifest or ():
        try:
            labels.append(load_label(entry, LABEL_DIR))
        except LabelError as exc:
            problems.append(f"Label_Snapshot {exc}")

    fixture: DemoFixture | None = None
    try:
        fixture = load_fixture(FIXTURE_PATH)
    except FixtureError as exc:
        problems.extend(
            f"Demo_Fixture {path}: {message}" for path, message in exc.problems)

    schema_sql = ""
    tables: dict[str, list[ColumnDef]] | None = None
    try:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        tables = parse_tables(schema_sql)
    except (OSError, ValueError) as exc:
        problems.append(f"Schema_File {SCHEMA_PATH}: {exc}")

    if fixture is not None and manifest is not None and tables is not None:
        problems.extend(
            f"{p.field} (Requirement {p.requirement}): {p.message}"
            for p in fixture_problems(fixture, labels, manifest, schema=tables)
        )
    if problems or fixture is None or manifest is None or tables is None:
        return None, problems

    notices: list[str] = []
    columns = {table: [column.name for column in cols]
               for table, cols in tables.items()}
    try:
        for loaded in labels:
            notices.extend(import_sections(loaded)[1])
        rows = build_rows(fixture, labels, manifest, columns)
        wire_rows = {table: [tuple(to_wire(value) for value in row.values()) for row in table_rows]
                     for table, table_rows in rows.items()}
    except (LabelError, ValueError, TypeError) as exc:
        return None, [f"Seed rows could not be built: {exc}"]
    return ValidatedInputs(fixture, manifest, labels, schema_sql, tables, rows, wire_rows, notices), []


# --- Database runs -----------------------------------------------------------------------------------


SCHEMA_APPLY_PROLOGUE = [
    f"CREATE SCHEMA IF NOT EXISTS {SEED_SCHEMA}", f"OPEN SCHEMA {SEED_SCHEMA}"]
SCHEMA_APPLY_STAYS_APPLIED = ("Statements executed before this failure stay applied. Fix the cause and re-run "
                              "--apply-schema; every statement is safe to repeat.")
SCHEMA_APPLY_SEED_SKIPPED = "The Default_Seed_Run was skipped."
SCHEMA_APPLY_MARKS = {
    LEGACY_DROP: "to be dropped",
    CANONICAL_REPLACE: "to be replaced empty",
    UNMANAGED: "unmanaged, left unchanged",
}
_SCHEMA_APPLY_TARGET_RE = re.compile(
    r"\bTABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?([A-Za-z_][\w.]*)", re.IGNORECASE)


def schema_apply(inputs: ValidatedInputs, *, connect_factory: ConnectFactory, out: TextIO, err: TextIO,
                 target: ConnectionTarget | None = None) -> int:
    """Schema_Apply on an autocommit connection: drop the Legacy_Tables, run the Schema_File in order.

    Steps (design "Schema_Apply"): refuse a Schema_File whose first two statements do not create and open
    MEDGUARD (exit 6, no connection); connect with autocommit on and a 30 s timeout (exit 4); print the
    target, the database version and every live MEDGUARD table with its row count and mark; drop each
    Legacy_Table as `MEDGUARD.<name>`; execute every Schema_File statement in file order, stopping at the
    first failure (exit 6, earlier statements stay applied); then check the result (exit 6 on a mismatch).
    Returns EXIT_OK when the caller should continue with the Default_Seed_Run. Unmanaged tables are only
    counted. Every printed error passes through the password redactor.
    """
    from hackathon26.join_verification import make_redactor

    statements = split_statements(inputs.schema_sql)
    # Requirement 16.3: unqualified tables must land in MEDGUARD
    if statements[:2] != SCHEMA_APPLY_PROLOGUE:
        print(f"Schema_Apply refused: the Schema_File {SCHEMA_PATH.name} must start with "
              f"'{SCHEMA_APPLY_PROLOGUE[0]};' and '{SCHEMA_APPLY_PROLOGUE[1]};'. No statement was executed.",
              file=err)
        return EXIT_SCHEMA_APPLY
    try:
        target = _default_target() if target is None else target
    except Exception as exc:  # unreadable deployment files or a malformed setting
        print(
            f"Could not resolve the Exasol connection settings: {make_redactor()(str(exc))}", file=err)
        print("No statement was executed.", file=err)
        return EXIT_CONNECT
    redact = make_redactor(target.password)
    where = f"{target.host}:{target.port}"
    try:
        conn = connect_factory(schema="", autocommit=True,
                               connection_timeout=CONNECTION_TIMEOUT_S)
    except Exception as exc:
        print(
            f"Could not connect to the Exasol Target_Database at {where}: {redact(str(exc))}", file=err)
        print("No statement was executed.", file=err)
        return EXIT_CONNECT
    try:
        return _schema_apply_steps(conn, inputs, statements, target=target, out=out, err=err, redact=redact)
    finally:
        _close(conn)


def _schema_apply_steps(conn, inputs: ValidatedInputs, statements: list[str], *, target: ConnectionTarget,
                        out: TextIO, err: TextIO, redact: Callable[[str], str]) -> int:
    # Steps 1 and 2: target and inventory, before any DROP or CREATE (Requirements 2.2, 2.3, 2.6).
    try:
        version = conn.execute("SELECT PARAM_VALUE FROM SYS.EXA_METADATA WHERE PARAM_NAME = {name}",
                               {"name": "databaseProductVersion"}).fetchval()
        live = _schema_apply_live_tables(conn)
        inventory = classify_live_tables(
            {t: set(cols) for t, cols in live.items()}, set(inputs.tables))
        counts = {table: _schema_apply_count(
            conn, table) for table in sorted(live)}
    except Exception as exc:
        print(
            f"Schema_Apply could not read the {SEED_SCHEMA} inventory: {redact(str(exc))}", file=err)
        print("No DROP or CREATE statement was executed.", file=err)
        return EXIT_SCHEMA_APPLY
    print(f"Schema_Apply: Target_Database {target.host}:{target.port}, Exasol {version}, "
          f"schema {SEED_SCHEMA}.", file=out)
    print("It drops the legacy tables and recreates every canonical table empty, CLINICIAN_REVIEW and "
          "AUDIT_LOG included. Tables it does not manage are left unchanged.", file=out)
    if not live:
        print(f"  {SEED_SCHEMA} holds no table yet.", file=out)
    for table in sorted(live):
        mark = inventory.marks[table]
        note = SCHEMA_APPLY_MARKS[mark]
        if mark is LEGACY_DROP and table in inputs.tables:
            note += " (legacy layout; the Schema_File recreates it empty)"
        print(
            f"  {SEED_SCHEMA}.{table}: {_rows(counts[table])}, {note}", file=out)
    to_create = [table for table in inputs.tables if table not in live]
    if to_create:
        print(
            f"  Not present yet, created by the Schema_File: {', '.join(to_create)}", file=out)

    # Steps 3 and 4: drops, then the Schema_File in file order; stop at the first failure (Requirement 2.8).
    steps = [(f"{SEED_SCHEMA}.{table}", "DROP TABLE IF EXISTS {table!i}", {"table": (SEED_SCHEMA, table)})
             for table in inventory.legacy_drop]
    steps += [(_schema_apply_target(statement), statement, None)
              for statement in statements]
    for shown, statement, params in steps:
        try:
            if params is None:
                conn.execute(statement)
            else:
                conn.execute(statement, params)
        except Exception as exc:
            print(
                f"Schema_Apply failed at {redact(shown)}: {redact(str(exc))}", file=err)
            print(SCHEMA_APPLY_STAYS_APPLIED, file=err)
            print(SCHEMA_APPLY_SEED_SKIPPED, file=err)
            return EXIT_SCHEMA_APPLY

    # Step 5: post-check (Requirement 2.5).
    try:
        problems = _schema_apply_post_check(conn, inputs)
    except Exception as exc:
        problems = [
            f"the check could not read {SEED_SCHEMA}: {redact(str(exc))}"]
    if problems:
        print(
            f"Schema_Apply ran every statement, but {SEED_SCHEMA} does not match the Schema_File:", file=err)
        for line in problems:
            print(f"  {redact(line)}", file=err)
        print(SCHEMA_APPLY_STAYS_APPLIED, file=err)
        print(SCHEMA_APPLY_SEED_SKIPPED, file=err)
        return EXIT_SCHEMA_APPLY
    print(f"Schema_Apply complete: {len(inputs.tables)} canonical tables match the Schema_File, the "
          "app-written tables are empty. Continuing with the Default_Seed_Run.", file=out)
    return EXIT_OK


def _schema_apply_live_tables(conn) -> dict[str, dict[str, str]]:
    """Live MEDGUARD tables (from SYS.EXA_ALL_TABLES) with their columns and COLUMN_TYPE values."""
    names = [row[0] for row in conn.execute(
        "SELECT TABLE_NAME FROM SYS.EXA_ALL_TABLES WHERE TABLE_SCHEMA = {schema}",
        {"schema": SEED_SCHEMA}).fetchall()]
    live: dict[str, dict[str, str]] = {name: {} for name in names}
    for table, column, column_type in conn.execute(
            "SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE FROM SYS.EXA_ALL_COLUMNS "
            "WHERE COLUMN_SCHEMA = {schema}", {"schema": SEED_SCHEMA}).fetchall():
        if table in live:  # views also have columns; only tables count
            live[table][column] = column_type
    return live


def _schema_apply_count(conn, table: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM {table!i}", {"table": (SEED_SCHEMA, table)}).fetchval())


def _schema_apply_target(statement: str) -> str:
    """The table a Schema_File statement targets, qualified with MEDGUARD, or the statement text."""
    match = _SCHEMA_APPLY_TARGET_RE.search(statement)
    if match is None:
        return statement[:200]
    name = match.group(1)
    return name if "." in name else f"{SEED_SCHEMA}.{name}"


def _schema_apply_post_check(conn, inputs: ValidatedInputs) -> list[str]:
    """Base types per Schema_File, no Legacy_Table name left and empty App_Written_Tables."""
    live = _schema_apply_live_tables(conn)
    problems = []
    for mismatch in compare_columns(inputs.tables, live, compare_types=True):
        name = f"{SEED_SCHEMA}.{mismatch.table}"
        if mismatch.table_missing:
            problems.append(f"{name}: table missing")
            continue
        parts = []
        if mismatch.missing:
            parts.append("missing columns " + ", ".join(mismatch.missing))
        if mismatch.unexpected:
            parts.append("unexpected columns " +
                         ", ".join(mismatch.unexpected))
        parts += [f"column {column} has base type {live_type}, the Schema_File defines {file_type}"
                  for column, file_type, live_type in mismatch.type_mismatches]
        problems.append(f"{name}: " + "; ".join(parts))
    problems += [f"{SEED_SCHEMA}.{table}: legacy table still present"
                 for table in sorted(LEGACY_TABLE_NAMES & set(live))]
    for table in inputs.tables:
        if table in SEED_OWNED_TABLES or table not in live:
            continue
        count = _schema_apply_count(conn, table)
        if count:
            problems.append(
                f"{SEED_SCHEMA}.{table}: holds {_rows(count)}, expected 0 after Schema_Apply")
    return problems


def _rows(count: int) -> str:
    return f"{count} row" if count == 1 else f"{count} rows"


def default_seed_run(inputs: ValidatedInputs, *, connect_factory: ConnectFactory, out: TextIO, err: TextIO,
                     target: ConnectionTarget | None = None,
                     evidence_source: EvidenceSource | None = None) -> int:
    """Default_Seed_Run in one transaction: column check, replace Seed_Owned rows, read back, verify join.

    Steps (design "Default_Seed_Run"): connect with autocommit off and a 30 s timeout (exit 4 on failure);
    check the live MEDGUARD columns against the Schema_File (exit 5) and the session NLS formats (exit 7),
    both before any write; DELETE then insert every Seed_Owned_Table in SEED_OWNED_TABLES order; read every
    DRUG_LABEL_SECTION back in the same transaction; COMMIT, or ROLLBACK and exit 7; print the row count of
    every Canonical_Table; then run Join_Verification on a fresh connection and exit 0 on EVIDENCE_FOUND or
    8 otherwise, leaving the committed rows in place.

    `target` (host, port and the password to redact) and `evidence_source` are resolved from
    `hackathon26.db` and `connect_factory` when not given; tests inject both.
    """
    from hackathon26.join_verification import make_redactor

    try:
        target = _default_target() if target is None else target
    except Exception as exc:  # unreadable deployment files or a malformed setting
        print(
            f"Could not resolve the Exasol connection settings: {make_redactor()(str(exc))}", file=err)
        print(NOTHING_WRITTEN, file=err)
        return EXIT_CONNECT
    redact = make_redactor(target.password)
    where = f"{target.host}:{target.port}"

    try:
        conn = connect_factory(schema="", autocommit=False,
                               connection_timeout=CONNECTION_TIMEOUT_S)
    except Exception as exc:  # no password, unreachable host, TLS or login failure, timeout
        print(
            f"Could not connect to the Exasol Target_Database at {where}: {redact(str(exc))}", file=err)
        print(NOTHING_WRITTEN, file=err)
        return EXIT_CONNECT
    print(
        f"Default_Seed_Run: connected to {where}; checking {SEED_SCHEMA} before writing.", file=out)
    try:
        status = _seed_transaction(
            conn, inputs, out=out, err=err, redact=redact)
    finally:
        _close(conn)
    if status != EXIT_OK:
        return status
    return _post_seed_verification(inputs.fixture, connect_factory=connect_factory, out=out, err=err,
                                   redact=redact, evidence_source=evidence_source)


NOTHING_WRITTEN = "No row was written."
ROLLED_BACK = ("Every row change of this run was rolled back; the Seed_Owned_Tables hold the rows they held "
               "before the run. Fix the cause and re-run the seed.")
APPLY_SCHEMA_HINT = (
    "Run `uv run python src/hackathon26/seed.py --apply-schema` to rebuild the canonical schema. "
    "It empties every canonical table, CLINICIAN_REVIEW and AUDIT_LOG included."
)
COMMIT_UNKNOWN = ("The outcome is unknown: the rows of this run may or may not be committed. "
                  "Re-running the seed is safe; it replaces the same rows.")


def _default_target() -> ConnectionTarget:
    """Host, port and password from `db.settings()`; host and port only when no password resolves."""
    from hackathon26 import db

    try:
        resolved = db.settings()
    except RuntimeError:
        # No password resolved. connect() raises the same error; still show where it would connect.
        deployment = db._deployment()
        return ConnectionTarget(os.getenv("EXASOL_HOST") or deployment.get("host") or "127.0.0.1",
                                os.getenv("EXASOL_PORT") or deployment.get("dbPort") or 8563)
    return ConnectionTarget(resolved["host"], resolved["port"], resolved["password"])


def _close(conn) -> None:
    try:
        conn.close()
    except Exception:  # closing never changes the outcome; Exasol discards uncommitted work on disconnect
        pass


def _rollback(conn, err: TextIO, redact: Callable[[str], str]) -> None:
    try:
        conn.rollback()
    except Exception as exc:
        print(f"ROLLBACK failed as well: {redact(str(exc))}. Closing the connection discards the uncommitted "
              "row changes.", file=err)


def _seed_transaction(conn, inputs: ValidatedInputs, *, out: TextIO, err: TextIO,
                      redact: Callable[[str], str]) -> int:
    """Checks, writes, storage round trip, COMMIT and counts on the one autocommit-off connection."""
    try:
        schema_found, mismatch_lines = _column_check(conn, inputs)
        nls_lines = _nls_problems(conn)
    except Exception as exc:
        print(f"Reading the {SEED_SCHEMA} definitions or the session formats failed: {redact(str(exc))}",
              file=err)
        print(NOTHING_WRITTEN, file=err)
        return EXIT_WRITE
    if not schema_found or mismatch_lines:  # Requirements 3.1, 3.2
        if not schema_found:
            print(f"The {SEED_SCHEMA} schema does not exist.", file=err)
        else:
            print(
                f"The live {SEED_SCHEMA} tables differ from the Schema_File {SCHEMA_PATH.name}:", file=err)
            for line in mismatch_lines:
                print(line, file=err)
        print(APPLY_SCHEMA_HINT, file=err)
        print(NOTHING_WRITTEN, file=err)
        return EXIT_COLUMNS
    if nls_lines:  # design step 2; no ALTER SESSION (Requirement 15.3)
        print("The session formats differ from the formats the seed writes DATE, TIMESTAMP and DECIMAL values "
              "in:", file=err)
        for line in nls_lines:
            print(line, file=err)
        print("The seed does not change session settings. Restore the database defaults and re-run.", file=err)
        print(NOTHING_WRITTEN, file=err)
        return EXIT_WRITE

    step = None
    try:
        for table in SEED_OWNED_TABLES:  # Requirements 3.3, 3.6: only the Seed_Owned_Tables, fixed order
            step = f"Writing {SEED_SCHEMA}.{table}"
            conn.execute("DELETE FROM {table!i}", {
                         "table": (SEED_SCHEMA, table)})
            rows = inputs.wire_rows[table]
            if rows:
                conn.ext.insert_multi((SEED_SCHEMA, table), rows,
                                      columns=[column.name for column in inputs.tables[table]])
        step = f"Reading {SEED_SCHEMA}.DRUG_LABEL_SECTION back"
        round_trip = _round_trip_problems(conn, inputs)
    except Exception as exc:  # Requirement 3.7
        _rollback(conn, err, redact)
        print(f"{step} failed: {redact(str(exc))}", file=err)
        print(ROLLED_BACK, file=err)
        return EXIT_WRITE
    if round_trip:  # Requirement 8.12
        _rollback(conn, err, redact)
        print(
            f"The storage round trip of {SEED_SCHEMA}.DRUG_LABEL_SECTION found a mismatch:", file=err)
        for line in round_trip:
            print(f"  {redact(line)}", file=err)
        print(ROLLED_BACK, file=err)
        return EXIT_WRITE
    try:
        conn.commit()
    except Exception as exc:
        print(f"COMMIT failed: {redact(str(exc))}", file=err)
        print(COMMIT_UNKNOWN, file=err)
        return EXIT_WRITE

    # Requirement 3.8
    print(f"Committed. Row counts in {SEED_SCHEMA}:", file=out)
    for table in inputs.tables:
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM {table!i}", {"table": (SEED_SCHEMA, table)}).fetchval()
            print(f"  {table}: {count}", file=out)
        except Exception as exc:  # the rows are committed; report the count as missing and go on
            print(f"  {table}: count unavailable ({redact(str(exc))})", file=out)
    return EXIT_OK


def _column_check(conn, inputs: ValidatedInputs) -> tuple[bool, list[str]]:
    """Whether MEDGUARD exists, and one line per Canonical_Table whose column names differ (order ignored)."""
    found = conn.execute("SELECT SCHEMA_NAME FROM SYS.EXA_SCHEMAS WHERE SCHEMA_NAME = {schema}",
                         {"schema": SEED_SCHEMA}).fetchall()
    if not found:
        return False, []
    live: dict[str, dict[str, str]] = {}
    for table, column, column_type in conn.execute(
            "SELECT COLUMN_TABLE, COLUMN_NAME, COLUMN_TYPE FROM SYS.EXA_ALL_COLUMNS "
            "WHERE COLUMN_SCHEMA = {schema}", {"schema": SEED_SCHEMA}).fetchall():
        live.setdefault(table, {})[column] = column_type
    lines = []
    for mismatch in compare_columns(inputs.tables, live):
        if mismatch.table_missing:
            lines.append(f"  {SEED_SCHEMA}.{mismatch.table}: table missing")
            continue
        parts = []
        if mismatch.missing:
            parts.append("missing columns " + ", ".join(mismatch.missing))
        if mismatch.unexpected:
            parts.append("unexpected columns " +
                         ", ".join(mismatch.unexpected))
        lines.append(f"  {SEED_SCHEMA}.{mismatch.table}: " + "; ".join(parts))
    return True, lines


def _nls_problems(conn) -> list[str]:
    session = dict(conn.execute(
        "SELECT PARAMETER_NAME, SESSION_VALUE FROM SYS.EXA_PARAMETERS").fetchall())
    lines = []
    for name, expected in NLS_EXPECTED.items():
        actual = session.get(name)
        shown = "not reported" if actual is None else f"'{actual}'"
        if actual != expected:
            lines.append(f"  {name} is {shown}, expected '{expected}'")
    return lines


def _round_trip_problems(conn, inputs: ValidatedInputs) -> list[str]:
    """Requirement 8.10: every written section comes back with identical text and a matching hash."""
    drug_names = {row["DRUG_ID"]: row["GENERIC_NAME"]
                  for row in inputs.rows["DRUG"]}
    read = {
        int(section_id): (text, sha)
        for section_id, text, sha in conn.execute(
            "SELECT SECTION_ID, SECTION_TEXT, CONTENT_SHA256 FROM MEDGUARD.DRUG_LABEL_SECTION "
            "ORDER BY SECTION_ID").fetchall()
    }
    problems = []
    for row in inputs.rows["DRUG_LABEL_SECTION"]:
        section_id = row["SECTION_ID"]
        drug = drug_names.get(row["DRUG_ID"], f"DRUG_ID {row['DRUG_ID']}")
        name = f"SECTION_ID {section_id} ({drug}, {row['SECTION_TYPE']})"
        if section_id not in read:
            problems.append(f"{name}: not read back")
            continue
        text, sha = read[section_id]
        if text != row["SECTION_TEXT"]:
            problems.append(
                f"{name}: the SECTION_TEXT read back differs from the text written")
        try:
            matches = text is not None and content_hash(text) == sha
        except LabelError:
            matches = False
        if not matches:
            problems.append(
                f"{name}: the CONTENT_SHA256 read back does not match the hash of the text read back")
    return problems


def _join_arguments(fixture: DemoFixture) -> tuple[int, date, int | None]:
    """Demo_Patient id, As_Of_Date and ibuprofen's DRUG_ID (Requirement 13.8), all from the Demo_Fixture."""
    drug_id = next(
        (drug.drug_id for drug in fixture.drugs if drug.generic_name == JOIN_CANDIDATE), None)
    return fixture.patient.patient_id, fixture.as_of, drug_id


SEED_ROWS_STAY = "The seed rows stay committed."
VERIFY_WROTE_NOTHING = "Verify_Mode wrote nothing."


def _post_seed_verification(fixture: DemoFixture, *, connect_factory: ConnectFactory, out: TextIO, err: TextIO,
                            redact: Callable[[str], str], evidence_source: EvidenceSource | None,
                            closing_note: str = SEED_ROWS_STAY) -> int:
    """Requirements 13.8, 13.9, 13.11: one Join_Status on a fresh connection; never rolls back the seed.

    Shared by the Default_Seed_Run and Verify_Mode so both print the same report; `closing_note` is the
    line printed after a status other than EVIDENCE_FOUND.
    """
    from hackathon26.evidence_check.repository import EvidenceRepository
    from hackathon26.join_verification import format_report, verify_join

    source = evidence_source if evidence_source is not None else EvidenceRepository(
        lambda: connect_factory(schema="", connection_timeout=CONNECTION_TIMEOUT_S))
    patient_id, as_of, drug_id = _join_arguments(fixture)
    try:
        verification = verify_join(
            patient_id, as_of, candidate_drug_id=drug_id, source=source, redact=redact)
    except Exception as exc:  # verify_join maps the known errors; anything else is still a failed check
        print(
            f"QUERY_FAILED\nJoin_Verification raised: {redact(str(exc))}\nClinician review required.", file=out)
        print(
            f"Join_Verification did not return EVIDENCE_FOUND. {closing_note}", file=err)
        return EXIT_JOIN
    print(redact(format_report(verification)), file=out)
    if verification.status == "EVIDENCE_FOUND":
        return EXIT_OK
    print(
        f"Join_Verification returned {verification.status}, not EVIDENCE_FOUND. {closing_note}", file=err)
    return EXIT_JOIN


def verify_mode(fixture: DemoFixture, *, connect_factory: ConnectFactory, out: TextIO, err: TextIO,
                target: ConnectionTarget | None = None, evidence_source: EvidenceSource | None = None) -> int:
    """Verify_Mode: run Join_Verification read-only and report one Join_Status. Writes nothing.

    Uses only the Demo_Fixture (patient id, As_Of_Date and ibuprofen's DRUG_ID); the caller has loaded it.
    Without an injected `evidence_source` it opens one autocommit connection with a 30 s timeout (exit 4
    with host, port and the redacted error if that fails) and runs the evidence repository's SELECTs on
    it, nothing else (Requirements 13.10, 15.3, 16.5). Prints the same report as the Default_Seed_Run and
    exits 0 on EVIDENCE_FOUND or 8 otherwise (Requirements 13.9, 13.11).
    """
    from hackathon26.join_verification import make_redactor

    try:
        target = _default_target() if target is None else target
    except Exception as exc:  # unreadable deployment files or a malformed setting
        print(
            f"Could not resolve the Exasol connection settings: {make_redactor()(str(exc))}", file=err)
        print(VERIFY_WROTE_NOTHING, file=err)
        return EXIT_CONNECT
    redact = make_redactor(target.password)
    where = f"{target.host}:{target.port}"
    print(f"Verify_Mode: Join_Verification against {SEED_SCHEMA} at {where}; reads only, writes nothing.",
          file=out)

    if evidence_source is not None:
        return _post_seed_verification(fixture, connect_factory=connect_factory, out=out, err=err,
                                       redact=redact, evidence_source=evidence_source,
                                       closing_note=VERIFY_WROTE_NOTHING)

    from hackathon26.evidence_check.repository import EvidenceRepository

    try:
        conn = connect_factory(schema="", autocommit=True,
                               connection_timeout=CONNECTION_TIMEOUT_S)
    # no password, unreachable host, TLS or login failure, timeout (Requirement 3.11)
    except Exception as exc:
        print(
            f"Could not connect to the Exasol Target_Database at {where}: {redact(str(exc))}", file=err)
        print(VERIFY_WROTE_NOTHING, file=err)
        return EXIT_CONNECT
    try:
        return _post_seed_verification(fixture, connect_factory=connect_factory, out=out, err=err,
                                       redact=redact, evidence_source=EvidenceRepository(
                                           lambda: conn),
                                       closing_note=VERIFY_WROTE_NOTHING)
    finally:
        # the repository closes it after its reads; this covers a join that sent no query
        _close(conn)


# --- Command line ------------------------------------------------------------------------------------


class _ParserExit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    """argparse that writes to the given streams and returns its exit status instead of exiting."""

    def __init__(self, *, out: TextIO, err: TextIO, **kwargs) -> None:
        super().__init__(**kwargs)
        self._out, self._err = out, err

    def _print_message(self, message: str, file=None) -> None:
        if message:
            (self._err if file is sys.stderr else self._out).write(message)

    def exit(self, status: int = 0, message: str | None = None):
        if message:
            self._err.write(message)
        raise _ParserExit(status)


def _parser(out: TextIO, err: TextIO) -> _Parser:
    parser = _Parser(
        out=out, err=err, prog="seed.py", allow_abbrev=False,
        description="Apply the canonical MEDGUARD schema, seed the synthetic demo data and verify the "
                    "evidence join. Inputs are validated offline before any connection is opened.",
    )
    parser.add_argument("--apply-schema", action="store_true",
                        help="drop the legacy tables and recreate every canonical table empty "
                             "(CLINICIAN_REVIEW and AUDIT_LOG included), then seed")
    parser.add_argument("--verify", action="store_true",
                        help="only run the evidence-join verification; writes nothing")
    # Retired. Handled before parsing; kept so argparse never suggests it.
    parser.add_argument("--reset", action="store_true", help=argparse.SUPPRESS)
    return parser


def _is_reset(arg: str) -> bool:
    return arg == "--reset" or arg.startswith("--reset=")


def main(argv: list[str] | None = None, *, connect_factory: ConnectFactory | None = None,
         out: TextIO | None = None, err: TextIO | None = None, target: ConnectionTarget | None = None,
         evidence_source: EvidenceSource | None = None) -> int:
    """Run the Seed_Command and return its exit status. Opens no connection before offline validation.

    `target` and `evidence_source` are passed to the Default_Seed_Run and Verify_Mode; when None they are resolved from
    `hackathon26.db` and `connect_factory` (tests inject them so no credentials resolve).
    """
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    connect_factory = _default_connect if connect_factory is None else connect_factory
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Requirement 15.4: --reset wins over every other option, valid or not.
    if any(_is_reset(arg) for arg in args_list):
        print(RESET_RETIRED, file=err)
        return EXIT_USAGE
    try:
        args = _parser(out, err).parse_args(args_list)
    except _ParserExit as exc:
        return exc.status
    if args.apply_schema and args.verify:  # Requirement 2.10
        print(CANNOT_COMBINE, file=err)
        return EXIT_USAGE

    if args.verify:
        try:
            fixture = load_fixture(FIXTURE_PATH)
        except FixtureError as exc:
            _print_problems(
                [f"Demo_Fixture {path}: {message}" for path, message in exc.problems], err)
            return EXIT_INPUT
        return verify_mode(fixture, connect_factory=connect_factory, out=out, err=err, target=target,
                           evidence_source=evidence_source)

    inputs, problems = validate_offline()
    if inputs is None:
        _print_problems(problems or ["the inputs could not be validated"], err)
        return EXIT_INPUT
    for notice in inputs.notices:
        print(notice, file=out)

    if args.apply_schema:
        status = schema_apply(
            inputs, connect_factory=connect_factory, out=out, err=err, target=target)
        if status != EXIT_OK:
            return status
    return default_seed_run(inputs, connect_factory=connect_factory, out=out, err=err, target=target,
                            evidence_source=evidence_source)


def _print_problems(problems: list[str], err: TextIO) -> None:
    print("Offline validation failed. No database connection was opened and no row was written.", file=err)
    for problem in problems:
        print(f"  - {problem}", file=err)


if __name__ == "__main__":
    sys.exit(main())
