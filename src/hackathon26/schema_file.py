"""Pure helpers for the Schema_File (`sql/01_schema.sql`).

Splits the file into statements, parses its table and column definitions, classifies the tables
found live in MEDGUARD and compares live columns with the file. Nothing here opens a file, a
connection or a socket: callers pass the SQL text and the rows they read from `SYS.EXA_ALL_COLUMNS`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

# Legacy tables of the retired six-table seed that are dropped by name alone.
LEGACY_TABLE_NAMES = frozenset({"DRUG_PRODUCT", "PRESCRIPTION", "DISPENSING", "REVIEW_QUEUE"})
# PATIENT and AUDIT_LOG are canonical names too; only their legacy layouts are dropped.
LEGACY_PATIENT_MARKER = frozenset({"LANGUAGE"})
LEGACY_AUDIT_LOG_MARKER = frozenset({"EVENT_ID", "ACTOR", "EVENT_ACTION"})


class TableMark(StrEnum):
    LEGACY_DROP = "LEGACY_DROP"
    CANONICAL_REPLACE = "CANONICAL_REPLACE"
    UNMANAGED = "UNMANAGED"


LEGACY_DROP = TableMark.LEGACY_DROP
CANONICAL_REPLACE = TableMark.CANONICAL_REPLACE
UNMANAGED = TableMark.UNMANAGED


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type_text: str  # e.g. "DECIMAL(10,0)", whitespace removed
    base_type: str  # type name without length, precision or scale, e.g. "DECIMAL"
    not_null: bool
    default: str | None
    in_primary_key: bool


@dataclass(frozen=True)
class TableInventory:
    marks: dict[str, TableMark]

    def _named(self, mark: TableMark) -> list[str]:
        return sorted(name for name, m in self.marks.items() if m is mark)

    @property
    def legacy_drop(self) -> list[str]:
        return self._named(TableMark.LEGACY_DROP)

    @property
    def canonical_replace(self) -> list[str]:
        return self._named(TableMark.CANONICAL_REPLACE)

    @property
    def unmanaged(self) -> list[str]:
        return self._named(TableMark.UNMANAGED)


@dataclass(frozen=True)
class ColumnMismatch:
    table: str
    missing: tuple[str, ...]  # in Schema_File order
    unexpected: tuple[str, ...]  # sorted
    table_missing: bool = False
    # (column, Schema_File base type, live base type); only filled when types are compared.
    type_mismatches: tuple[tuple[str, str, str], ...] = field(default=())


_COMMENT_RE = re.compile(r"--[^\n]*")
_CREATE_TABLE_ANY_RE = re.compile(r"\ACREATE\b.*?\bTABLE\b", re.IGNORECASE | re.DOTALL)
_CREATE_TABLE_RE = re.compile(
    r"\ACREATE\s+OR\s+REPLACE\s+TABLE\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<body>.*)\)\Z",
    re.IGNORECASE | re.DOTALL,
)
_PRIMARY_KEY_RE = re.compile(r"\APRIMARY\s+KEY\s*\((?P<cols>[^()]*)\)\Z", re.IGNORECASE)
_COLUMN_RE = re.compile(
    r"\A(?P<name>[A-Za-z_]\w*)\s+"
    r"(?P<type>[A-Za-z_]\w*(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)"
    r"(?:\s+DEFAULT\s+(?P<default>\S+))?"
    r"(?P<not_null>\s+NOT\s+NULL)?\Z",
    re.IGNORECASE | re.DOTALL,
)
_RESERVED_ITEM_WORDS = frozenset({"CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "DISTRIBUTE",
                                  "PARTITION", "LIKE"})


def split_statements(sql: str) -> list[str]:
    """Remove `--` comments, split on `;`, strip each piece and drop empty pieces.

    String literals are rejected, because a `--` or `;` inside one would be split wrongly.
    """
    without_comments = _COMMENT_RE.sub("", sql)
    if "'" in without_comments:
        raise ValueError("Schema_File contains a quote (') outside comments; string literals are not supported")
    pieces = (piece.strip() for piece in without_comments.split(";"))
    return [piece for piece in pieces if piece]


def _split_top_level(body: str) -> list[str]:
    items, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError(f"unbalanced parentheses in table body: {body!r}")
        elif ch == "," and depth == 0:
            items.append(body[start:i])
            start = i + 1
    if depth != 0:
        raise ValueError(f"unbalanced parentheses in table body: {body!r}")
    items.append(body[start:])
    return [" ".join(item.split()) for item in items]


def _parse_table(name: str, body: str) -> list[ColumnDef]:
    columns: list[tuple[str, str, bool, str | None]] = []
    primary_key: list[str] | None = None
    for item in _split_top_level(body):
        if not item:
            raise ValueError(f"{name}: empty column definition")
        pk = _PRIMARY_KEY_RE.match(item)
        if pk:
            if primary_key is not None:
                raise ValueError(f"{name}: more than one PRIMARY KEY clause")
            primary_key = [c.strip() for c in pk.group("cols").split(",")]
            continue
        match = _COLUMN_RE.match(item)
        if not match or match.group("name").upper() in _RESERVED_ITEM_WORDS:
            raise ValueError(f"{name}: unsupported table element {item!r}")
        type_text = re.sub(r"\s+", "", match.group("type")).upper()
        columns.append((match.group("name"), type_text, bool(match.group("not_null")), match.group("default")))

    names = [c[0] for c in columns]
    if len(set(names)) != len(names):
        raise ValueError(f"{name}: duplicate column name")
    pk_members = set(primary_key or ())
    if primary_key is not None and (len(pk_members) != len(primary_key) or not pk_members <= set(names)):
        raise ValueError(f"{name}: PRIMARY KEY {primary_key} must list distinct defined columns")
    return [
        ColumnDef(col, type_text, type_text.split("(", 1)[0], not_null, default, col in pk_members)
        for col, type_text, not_null, default in columns
    ]


def parse_tables(sql: str) -> dict[str, list[ColumnDef]]:
    """Return each `CREATE OR REPLACE TABLE` of the SQL text with its columns, both in file order."""
    tables: dict[str, list[ColumnDef]] = {}
    for statement in split_statements(sql):
        if not _CREATE_TABLE_ANY_RE.match(statement):
            continue
        match = _CREATE_TABLE_RE.match(statement)
        if not match:
            raise ValueError(f"unsupported CREATE TABLE form: {statement[:80]!r}")
        name = match.group("name")
        if name in tables:
            raise ValueError(f"table {name} is defined twice")
        tables[name] = _parse_table(name, match.group("body"))
    return tables


def live_base_type(column_type: str) -> str:
    """Base type of a `SYS.EXA_ALL_COLUMNS.COLUMN_TYPE`: text before the first `(` or space."""
    base = re.split(r"[(\s]", column_type.strip(), maxsplit=1)[0].upper()
    if not base:
        raise ValueError(f"cannot read a base type from {column_type!r}")
    return base


def classify_live_tables(live: dict[str, set[str]], canonical: set[str]) -> TableInventory:
    """Mark each live table (name -> column names) LEGACY_DROP, CANONICAL_REPLACE or UNMANAGED."""
    marks: dict[str, TableMark] = {}
    for table, cols in live.items():
        columns = set(cols)
        if (
            table in LEGACY_TABLE_NAMES
            or (table == "PATIENT" and LEGACY_PATIENT_MARKER <= columns)
            or (table == "AUDIT_LOG" and LEGACY_AUDIT_LOG_MARKER <= columns)
        ):
            marks[table] = TableMark.LEGACY_DROP
        elif table in canonical:
            marks[table] = TableMark.CANONICAL_REPLACE
        else:
            marks[table] = TableMark.UNMANAGED
    return TableInventory(marks)


def compare_columns(
    expected: dict[str, list[ColumnDef]],
    live: dict[str, dict[str, str]],
    *,
    compare_types: bool = False,
) -> list[ColumnMismatch]:
    """Compare each expected table with the live columns (table -> column -> COLUMN_TYPE).

    Column order is ignored and live tables not in `expected` do not count. Returns one entry per
    mismatched table, in `expected` order; an empty list means every table matches.
    """
    mismatches: list[ColumnMismatch] = []
    for table, columns in expected.items():
        names = [c.name for c in columns]
        if table not in live:
            mismatches.append(ColumnMismatch(table, tuple(names), (), table_missing=True))
            continue
        live_columns = live[table]
        missing = tuple(n for n in names if n not in live_columns)
        unexpected = tuple(sorted(set(live_columns) - set(names)))
        type_mismatches: tuple[tuple[str, str, str], ...] = ()
        if compare_types:
            type_mismatches = tuple(
                (c.name, c.base_type, live_base_type(live_columns[c.name]))
                for c in columns
                if c.name in live_columns and live_base_type(live_columns[c.name]) != c.base_type
            )
        if missing or unexpected or type_mismatches:
            mismatches.append(ColumnMismatch(table, missing, unexpected, type_mismatches=type_mismatches))
    return mismatches
