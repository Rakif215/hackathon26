"""Unit tests for the pure Schema_File helpers (offline: no database, no network)."""
import re
from pathlib import Path

import pytest

from hackathon26.schema_file import (
    CANONICAL_REPLACE,
    LEGACY_DROP,
    UNMANAGED,
    ColumnDef,
    ColumnMismatch,
    classify_live_tables,
    compare_columns,
    live_base_type,
    parse_tables,
    split_statements,
)

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "sql" / "01_schema.sql"


@pytest.fixture(scope="module")
def schema_sql() -> str:
    return SCHEMA_FILE.read_text(encoding="utf-8")


# --- split_statements -------------------------------------------------------------------------


def test_split_removes_comments_splits_on_semicolon_and_drops_empty_pieces():
    sql = (
        "-- header; with a semicolon\n"
        "CREATE SCHEMA IF NOT EXISTS S; -- trailing; comment\n"
        ";;\n"
        "  OPEN SCHEMA S  ;\n"
        "CREATE OR REPLACE TABLE T (\n"
        "    A DECIMAL(10,0), -- note; here\n"
        "    PRIMARY KEY (A)\n"
        ");\n"
        "-- final comment;\n"
    )
    assert split_statements(sql) == [
        "CREATE SCHEMA IF NOT EXISTS S",
        "OPEN SCHEMA S",
        "CREATE OR REPLACE TABLE T (\n    A DECIMAL(10,0), \n    PRIMARY KEY (A)\n)",
    ]


def test_split_ignores_semicolon_in_finding_comment(schema_sql):
    # The FINDING comment reads "DRUG_LABEL_SECTION; the loader verifies this ...".
    assert "DRUG_LABEL_SECTION; the loader verifies" in schema_sql
    statements = split_statements(schema_sql)
    assert not any("loader verifies" in s for s in statements)
    assert not any("--" in s for s in statements)
    finding = [s for s in statements if "TABLE FINDING " in s]
    assert len(finding) == 1 and finding[0].startswith(
        "CREATE OR REPLACE TABLE FINDING (")


def test_split_real_file_starts_with_schema_statements(schema_sql):
    statements = split_statements(schema_sql)
    assert statements[:2] == [
        "CREATE SCHEMA IF NOT EXISTS MEDGUARD", "OPEN SCHEMA MEDGUARD"]
    assert all(s.startswith("CREATE OR REPLACE TABLE ")
               for s in statements[2:])


def test_split_rejects_string_literals_outside_comments():
    with pytest.raises(ValueError, match="quote"):
        split_statements(
            "CREATE OR REPLACE TABLE T (A VARCHAR(5) DEFAULT 'a;b');")
    # A quote inside a comment is harmless because comments are removed first.
    assert split_statements(
        "-- it's fine\nOPEN SCHEMA S;") == ["OPEN SCHEMA S"]


# --- parse_tables -----------------------------------------------------------------------------


def test_parse_tables_returns_column_defs_in_file_order():
    sql = """
    CREATE OR REPLACE TABLE ZETA (
        Z_ID     DECIMAL(10,0),
        LABEL    VARCHAR(200) NOT NULL,     -- comment, with comma
        FLAG     BOOLEAN DEFAULT FALSE,
        HASH     CHAR(64)     NOT NULL,
        PRIMARY KEY (Z_ID, LABEL)
    );
    CREATE OR REPLACE TABLE ALPHA (
        A_ID DECIMAL(4,0) DEFAULT 0 NOT NULL,
        AT   TIMESTAMP
    );
    """
    tables = parse_tables(sql)
    assert list(tables) == ["ZETA", "ALPHA"]
    assert tables["ZETA"] == [
        ColumnDef("Z_ID", "DECIMAL(10,0)", "DECIMAL", False, None, True),
        ColumnDef("LABEL", "VARCHAR(200)", "VARCHAR", True, None, True),
        ColumnDef("FLAG", "BOOLEAN", "BOOLEAN", False, "FALSE", False),
        ColumnDef("HASH", "CHAR(64)", "CHAR", True, None, False),
    ]
    assert tables["ALPHA"] == [
        ColumnDef("A_ID", "DECIMAL(4,0)", "DECIMAL", True, "0", False),
        ColumnDef("AT", "TIMESTAMP", "TIMESTAMP", False, None, False),
    ]


def test_parse_tables_on_real_file_reads_unchanged_tables(schema_sql):
    tables = parse_tables(schema_sql)
    assert tables["DRUG"] == [
        ColumnDef("DRUG_ID", "DECIMAL(10,0)", "DECIMAL", False, None, True),
        ColumnDef("RXCUI", "VARCHAR(20)", "VARCHAR", False, None, False),
        ColumnDef("GENERIC_NAME", "VARCHAR(200)",
                  "VARCHAR", True, None, False),
        ColumnDef("BRAND_NAMES", "VARCHAR(500)",
                  "VARCHAR", False, None, False),
        ColumnDef("IS_OTC", "BOOLEAN", "BOOLEAN", False, "FALSE", False),
        ColumnDef("SRC_NAME", "VARCHAR(100)", "VARCHAR", False, None, False),
        ColumnDef("SOURCE_FETCHED_AT", "TIMESTAMP",
                  "TIMESTAMP", False, None, False),
    ]
    assert [c.name for c in tables["PATIENT"]] == [
        "PATIENT_ID", "DISPLAY_NAME", "BIRTH_YEAR", "SEX", "PRIMARY_DX", "IS_SYNTHETIC",
    ]
    assert tables["PATIENT"][-1].default == "TRUE"
    # Tables without a PRIMARY KEY clause have no PK members.
    assert not any(c.in_primary_key for c in tables["DRUG_CLASS"])


@pytest.mark.parametrize("sql", [
    "CREATE OR REPLACE TABLE T (A DECIMAL(10,0), FOREIGN KEY (A) REFERENCES U (B));",
    "CREATE OR REPLACE TABLE T (A DECIMAL(10,0), PRIMARY KEY (MISSING));",
    "CREATE OR REPLACE TABLE T (A DECIMAL(10,0), A VARCHAR(5));",
    "CREATE OR REPLACE TABLE T (A DECIMAL(10,0)); CREATE OR REPLACE TABLE T (B DATE);",
    "CREATE OR REPLACE TABLE T (A DECIMAL(10,0) UNIQUE);",
])
def test_parse_tables_rejects_unsupported_or_inconsistent_definitions(sql):
    with pytest.raises(ValueError):
        parse_tables(sql)


# --- live base types --------------------------------------------------------------------------


@pytest.mark.parametrize("column_type,expected", [
    ("VARCHAR(100) UTF8", "VARCHAR"),
    ("TIMESTAMP(3)", "TIMESTAMP"),
    ("CHAR(64) UTF8", "CHAR"),
    ("DECIMAL(10,0)", "DECIMAL"),
    ("BOOLEAN", "BOOLEAN"),
    ("DATE", "DATE"),
])
def test_live_base_type_drops_length_precision_and_charset(column_type, expected):
    assert live_base_type(column_type) == expected


# --- classify_live_tables ---------------------------------------------------------------------

CANONICAL = {"DRUG", "PATIENT", "AUDIT_LOG", "FINDING"}


def test_classify_marks_legacy_canonical_and_unmanaged_tables():
    live = {
        "DRUG_PRODUCT": {"PRODUCT_ID"},
        "PRESCRIPTION": {"RX_ID"},
        "DISPENSING": {"DISPENSE_ID"},
        "REVIEW_QUEUE": {"QUEUE_ID"},
        "PATIENT": {"PATIENT_ID", "LANGUAGE"},
        "AUDIT_LOG": {"EVENT_ID", "ACTOR", "EVENT_ACTION", "DETAIL"},
        "DRUG": {"DRUG_ID"},
        "FINDING": {"FINDING_ID"},
        "TEAM_NOTES": {"NOTE"},
    }
    inventory = classify_live_tables(live, CANONICAL)
    assert inventory.marks == {
        "DRUG_PRODUCT": LEGACY_DROP,
        "PRESCRIPTION": LEGACY_DROP,
        "DISPENSING": LEGACY_DROP,
        "REVIEW_QUEUE": LEGACY_DROP,
        "PATIENT": LEGACY_DROP,
        "AUDIT_LOG": LEGACY_DROP,
        "DRUG": CANONICAL_REPLACE,
        "FINDING": CANONICAL_REPLACE,
        "TEAM_NOTES": UNMANAGED,
    }
    assert inventory.legacy_drop == [
        "AUDIT_LOG", "DISPENSING", "DRUG_PRODUCT", "PATIENT", "PRESCRIPTION", "REVIEW_QUEUE",
    ]
    assert inventory.canonical_replace == ["DRUG", "FINDING"]
    assert inventory.unmanaged == ["TEAM_NOTES"]


def test_classify_canonical_layout_patient_and_audit_log_are_replaced_not_dropped():
    live = {
        "PATIENT": {"PATIENT_ID", "DISPLAY_NAME", "IS_SYNTHETIC"},
        "AUDIT_LOG": {"AUDIT_ID", "EVENT_TYPE", "DETAIL"},
        # Only part of the legacy AUDIT_LOG layout: not the legacy table.
    }
    assert classify_live_tables(live, CANONICAL).marks == {
        "PATIENT": CANONICAL_REPLACE,
        "AUDIT_LOG": CANONICAL_REPLACE,
    }
    partial = {"AUDIT_LOG": {"AUDIT_ID", "EVENT_ID", "ACTOR"}}
    assert classify_live_tables(partial, CANONICAL).marks == {
        "AUDIT_LOG": CANONICAL_REPLACE}


def test_classify_is_case_sensitive_and_ignores_unlisted_tables():
    live = {"drug_product": {"X"}, "Patient": {"LANGUAGE"}}
    assert classify_live_tables(live, CANONICAL).marks == {
        "drug_product": UNMANAGED,
        "Patient": UNMANAGED,
    }
    assert classify_live_tables({}, CANONICAL).marks == {}


# --- compare_columns --------------------------------------------------------------------------


def _col(name: str, base: str = "DECIMAL") -> ColumnDef:
    return ColumnDef(name, base, base, False, None, False)


EXPECTED = {
    "DRUG": [_col("DRUG_ID"), _col("GENERIC_NAME", "VARCHAR"), _col("IS_OTC", "BOOLEAN")],
    "PATIENT": [_col("PATIENT_ID"), _col("DISPLAY_NAME", "VARCHAR")],
    "FINDING": [_col("FINDING_ID")],
}


def test_compare_columns_ignores_order_and_reports_nothing_on_match():
    live = {
        "DRUG": {"IS_OTC": "BOOLEAN", "GENERIC_NAME": "VARCHAR(200) UTF8", "DRUG_ID": "DECIMAL(10,0)"},
        "PATIENT": {"DISPLAY_NAME": "VARCHAR(100) UTF8", "PATIENT_ID": "DECIMAL(10,0)"},
        "FINDING": {"FINDING_ID": "DECIMAL(10,0)"},
        # non-canonical tables do not affect the check
        "TEAM_NOTES": {"NOTE": "VARCHAR(10) UTF8"},
    }
    assert compare_columns(EXPECTED, live) == []


def test_compare_columns_reports_missing_and_unexpected_names_per_table():
    live = {
        "DRUG": {"DRUG_ID": "DECIMAL(10,0)", "GENERIC_NAME": "VARCHAR(200) UTF8", "LEGACY": "DATE"},
        "PATIENT": {"PATIENT_ID": "DECIMAL(10,0)", "LANGUAGE": "VARCHAR(5) UTF8"},
    }
    assert compare_columns(EXPECTED, live) == [
        ColumnMismatch("DRUG", missing=("IS_OTC",), unexpected=("LEGACY",)),
        ColumnMismatch("PATIENT", missing=("DISPLAY_NAME",),
                       unexpected=("LANGUAGE",)),
        ColumnMismatch("FINDING", missing=("FINDING_ID",),
                       unexpected=(), table_missing=True),
    ]


def test_compare_columns_checks_base_types_only_when_asked():
    live = {
        "DRUG": {"DRUG_ID": "DECIMAL(18,0)", "GENERIC_NAME": "CHAR(200) UTF8", "IS_OTC": "BOOLEAN"},
        "PATIENT": {"PATIENT_ID": "DECIMAL(10,0)", "DISPLAY_NAME": "VARCHAR(100) UTF8"},
        "FINDING": {"FINDING_ID": "DECIMAL(10,0)"},
    }
    assert compare_columns(EXPECTED, live) == []
    assert compare_columns(EXPECTED, live, compare_types=True) == [
        ColumnMismatch("DRUG", missing=(), unexpected=(),
                       type_mismatches=(("GENERIC_NAME", "VARCHAR", "CHAR"),)),
    ]


def test_compare_columns_against_parsed_real_file(schema_sql):
    expected = parse_tables(schema_sql)
    live = {
        table: {c.name: c.type_text + (" UTF8" if c.base_type in {"VARCHAR", "CHAR"} else "")
                for c in reversed(cols)}
        for table, cols in expected.items()
    }
    assert compare_columns(expected, live, compare_types=True) == []


# --- demo-data-foundation adjustments on the real Schema_File (Requirements 1.1-1.8, 1.11, 2.9) ---

BEFORE_FILE = Path(__file__).resolve(
).parents[1] / "fixtures" / "schema_before_feature.sql"
MATCH_LEVEL_CODES = ["NAME_MATCH", "COLOUR_SHAPE_MATCH",
                     "COLOUR_MATCH", "CLASS_INFERRED", "UNRESOLVED"]
SEED_OWNED_TABLES = [
    "DRUG", "DRUG_CLASS", "CLASS_SYNONYM", "DRUG_LABEL_SECTION", "DRUG_APPEARANCE", "PATIENT",
    "PATIENT_MEDICATION", "LAB_RESULT", "RISK_LAB_RULE", "RISK_RULE_CLASS", "CONSULTATION", "UTTERANCE",
]
APP_WRITTEN_TABLES = ["DRUG_MENTION", "MENTION_CANDIDATE",
                      "FINDING", "CLINICIAN_REVIEW", "AUDIT_LOG"]
# Columns this feature adds, by table, with their exact definitions.
ADDED_COLUMNS = {
    "DRUG_LABEL_SECTION": [ColumnDef("CONTENT_SHA256", "CHAR(64)", "CHAR", True, None, False)],
    "RISK_LAB_RULE": [
        ColumnDef("EVIDENCE_SECTION_ID", "DECIMAL(10,0)",
                  "DECIMAL", True, None, False),
        ColumnDef("EVIDENCE_QUOTE", "VARCHAR(4000)",
                  "VARCHAR", True, None, False),
    ],
    "DRUG_MENTION": [
        ColumnDef("RESOLVED_CLASS_NAME", "VARCHAR(200)",
                  "VARCHAR", False, None, False),
        ColumnDef("MATCH_LEVEL", "VARCHAR(30)", "VARCHAR", True, None, False),
    ],
    "MENTION_CANDIDATE": [ColumnDef("MATCH_LEVEL", "VARCHAR(30)", "VARCHAR", True, None, False)],
    "FINDING": [ColumnDef("MATCH_LEVEL", "VARCHAR(30)", "VARCHAR", True, None, False)],
}
REMOVED_COLUMNS = {"DRUG_MENTION": {"CONFIDENCE"},
                   "MENTION_CANDIDATE": {"SCORE"}, "FINDING": {"CONFIDENCE"}}


@pytest.fixture(scope="module")
def tables(schema_sql) -> dict[str, list[ColumnDef]]:
    return parse_tables(schema_sql)


def _columns(tables, table: str) -> dict[str, ColumnDef]:
    return {c.name: c for c in tables[table]}


def _comment_above(lines: list[str], index: int) -> list[str]:
    """Comment lines directly above lines[index], top to bottom, with the `--` removed."""
    above: list[str] = []
    i = index - 1
    while i >= 0 and lines[i].strip().startswith("--"):
        above.insert(0, lines[i].strip()[2:].strip())
        i -= 1
    return above


def _table_block(sql: str, table: str) -> list[str]:
    match = re.search(
        rf"^CREATE OR REPLACE TABLE {table} \(\n(.*?)^\);", sql, re.MULTILINE | re.DOTALL)
    assert match, f"table {table} not found"
    return match.group(1).splitlines()


def _column_comment(sql: str, table: str, column: str) -> str:
    """The `--` comment beside a column: lines directly above it plus the same-line comment."""
    lines = _table_block(sql, table)
    hits = [i for i, line in enumerate(
        lines) if re.match(rf"\s*{column}\s", line)]
    assert len(hits) == 1, f"{table}.{column} defined {len(hits)} times"
    line = lines[hits[0]]
    same_line = line.split("--", 1)[1].strip() if "--" in line else ""
    return " ".join([*_comment_above(lines, hits[0]), same_line]).strip()


def _table_comment(sql: str, table: str) -> str:
    lines = sql.splitlines()
    index = lines.index(f"CREATE OR REPLACE TABLE {table} (")
    return " ".join(_comment_above(lines, index))


def test_drug_label_section_has_content_hash_column(tables, schema_sql):
    assert _columns(tables, "DRUG_LABEL_SECTION")[
        "CONTENT_SHA256"] == ADDED_COLUMNS["DRUG_LABEL_SECTION"][0]
    comment = _column_comment(
        schema_sql, "DRUG_LABEL_SECTION", "CONTENT_SHA256")
    assert "Added" in comment and "SHA-256" in comment and "SECTION_TEXT" in comment


def test_section_type_comment_lists_warnings_and_cautions(schema_sql):
    comment = _column_comment(schema_sql, "DRUG_LABEL_SECTION", "SECTION_TYPE")
    assert re.findall(r"\w+", comment) == [
        "boxed_warning", "contraindications", "warnings", "warnings_and_cautions", "drug_interactions",
    ]


def test_risk_rule_class_has_composite_primary_key(tables, schema_sql):
    assert tables["RISK_RULE_CLASS"] == [
        ColumnDef("RULE_ID", "DECIMAL(10,0)", "DECIMAL", True, None, True),
        ColumnDef("CLASS_NAME", "VARCHAR(200)", "VARCHAR", True, None, True),
    ]
    assert "PRIMARY KEY (RULE_ID, CLASS_NAME)" in schema_sql
    comment = _table_comment(schema_sql, "RISK_RULE_CLASS")
    assert "Added" in comment and "classes" in comment
    # Placed directly after RISK_LAB_RULE.
    names = list(tables)
    assert names.index("RISK_RULE_CLASS") == names.index("RISK_LAB_RULE") + 1


def test_risk_lab_rule_has_evidence_columns_and_no_foreign_key(tables, schema_sql):
    columns = _columns(tables, "RISK_LAB_RULE")
    assert [columns["EVIDENCE_SECTION_ID"],
            columns["EVIDENCE_QUOTE"]] == ADDED_COLUMNS["RISK_LAB_RULE"]
    section_comment = _column_comment(
        schema_sql, "RISK_LAB_RULE", "EVIDENCE_SECTION_ID")
    assert "Added" in section_comment and "DRUG_LABEL_SECTION" in section_comment
    assert "No FOREIGN KEY" in section_comment
    quote_comment = _column_comment(
        schema_sql, "RISK_LAB_RULE", "EVIDENCE_QUOTE")
    assert "Added" in quote_comment and "verbatim" in quote_comment and "substring" in quote_comment
    statements = " ".join(split_statements(schema_sql)).upper()
    assert "FOREIGN" not in statements and "REFERENCES" not in statements


@pytest.mark.parametrize("table,replaced", [
    ("DRUG_MENTION", "CONFIDENCE"),
    ("MENTION_CANDIDATE", "SCORE"),
    ("FINDING", "CONFIDENCE"),
])
def test_match_level_replaces_numeric_confidence(tables, schema_sql, table, replaced):
    columns = _columns(tables, table)
    assert columns["MATCH_LEVEL"] == ColumnDef(
        "MATCH_LEVEL", "VARCHAR(30)", "VARCHAR", True, None, False)
    assert replaced not in columns
    comment = _column_comment(schema_sql, table, "MATCH_LEVEL")
    assert "Added" in comment
    assert f"numeric {replaced} column" in comment
    codes = re.findall(
        r"\b(?:NAME_MATCH|COLOUR_SHAPE_MATCH|COLOUR_MATCH|CLASS_INFERRED|UNRESOLVED)\b", comment)
    assert codes == MATCH_LEVEL_CODES


def test_finding_match_level_comment_separates_trigger_drug_from_match_basis(schema_sql):
    comment = _column_comment(schema_sql, "FINDING", "MATCH_LEVEL")
    assert "mention that identified TRIGGER_DRUG_ID" in comment
    assert "MATCH_BASIS separately records how the label evidence was matched" in comment


def test_drug_mention_has_nullable_resolved_class_name(tables, schema_sql):
    column = _columns(tables, "DRUG_MENTION")["RESOLVED_CLASS_NAME"]
    assert column == ColumnDef(
        "RESOLVED_CLASS_NAME", "VARCHAR(200)", "VARCHAR", False, None, False)
    comment = _column_comment(
        schema_sql, "DRUG_MENTION", "RESOLVED_CLASS_NAME")
    assert "Added" in comment and "DRUG_CLASS.CLASS_NAME" in comment


def test_every_other_column_is_unchanged_from_the_16_table_file(tables):
    before = parse_tables(BEFORE_FILE.read_text(encoding="utf-8"))
    assert len(before) == 16
    assert set(tables) == set(before) | {"RISK_RULE_CLASS"}
    for table, before_columns in before.items():
        added = {c.name for c in ADDED_COLUMNS.get(table, [])}
        kept_before = {
            c.name: c for c in before_columns if c.name not in REMOVED_COLUMNS.get(table, set())}
        kept_after = {c.name: c for c in tables[table] if c.name not in added}
        assert kept_after == kept_before, table
        assert REMOVED_COLUMNS.get(table, set()) <= {
            c.name for c in before_columns}
        # Added columns really are new.
        assert not added & {c.name for c in before_columns}, table


def test_schema_file_defines_exactly_17_tables(tables, schema_sql):
    assert list(tables) == [*SEED_OWNED_TABLES[:9], "RISK_RULE_CLASS", *SEED_OWNED_TABLES[10:],
                            *APP_WRITTEN_TABLES]
    assert len(tables) == 17
    header = schema_sql.split("CREATE SCHEMA", 1)[0]
    assert "17 tables" in header and "16" not in header


def test_schema_file_statements_are_idempotent_and_quote_free(schema_sql):
    without_comments = re.sub(r"--[^\n]*", "", schema_sql)
    assert "'" not in without_comments
    statements = split_statements(schema_sql)
    assert statements[:2] == [
        "CREATE SCHEMA IF NOT EXISTS MEDGUARD", "OPEN SCHEMA MEDGUARD"]
    assert len(statements) == 2 + 17
    for statement in statements[2:]:
        assert statement.startswith("CREATE OR REPLACE TABLE "), statement[:60]
