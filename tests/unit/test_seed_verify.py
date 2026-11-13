"""Verify_Mode (`--verify`) offline: no network, no database.

Verify_Mode loads only the Demo_Fixture, runs Join_Verification for the Demo_Patient, 2026-11-13 and
ibuprofen's DRUG_ID, prints `format_report` and exits 0 on EVIDENCE_FOUND or 8 otherwise. It writes
nothing. The read-only test runs the real `EvidenceRepository` over a recording fake connection, so the
recorded SQL is what the server would receive. Credentials and the target host are injected.
Requirements 3.11, 13.9, 13.10, 13.11, 15.3, 16.5, 16.6.
"""
from __future__ import annotations

import io
import json
import re
from datetime import date
from types import SimpleNamespace

import pytest
from test_seed_run import FORMATTER, SENTINEL, TARGET, FakeDb, FakeEvidence, Result, found_rows

from hackathon26 import seed
from hackathon26.evidence_check.models import EvidenceRow
from hackathon26.evidence_check.repository import EvidenceStoreUnavailable
from hackathon26.join_verification import JoinVerification, format_report
from hackathon26.resolution.repository import UnknownPatient

NOT_READ_ONLY_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|RENAME|GRANT|REVOKE|COMMIT|ROLLBACK)\b",
    re.IGNORECASE)


@pytest.fixture(scope="module")
def inputs() -> seed.ValidatedInputs:
    validated, problems = seed.validate_offline()
    assert problems == [] and validated is not None
    return validated


@pytest.fixture
def only_fixture(monkeypatch):
    """Point every input except the Demo_Fixture at a missing path and forbid the full offline validation."""
    missing = seed.REPO / "does-not-exist"
    monkeypatch.setattr(seed, "MANIFEST_PATH", missing / "label_manifest.json")
    monkeypatch.setattr(seed, "LABEL_DIR", missing / "labels")
    monkeypatch.setattr(seed, "SCHEMA_PATH", missing / "01_schema.sql")

    def forbidden():
        raise AssertionError("Verify_Mode must load only the Demo_Fixture")

    monkeypatch.setattr(seed, "validate_offline", forbidden)


class RecordingConnection:
    """Answers the three evidence-repository reads and records every statement and transaction call."""

    def __init__(self, log: list, rows: list[EvidenceRow]) -> None:
        self.log, self.rows = log, rows
        self.ext = SimpleNamespace(
            insert_multi=lambda *a, **k: log.append(("insert_multi", a, k)))

    def execute(self, query, query_params=None):
        sql = query if query_params is None else FORMATTER.format(
            query, **query_params)
        self.log.append(("sql", sql))
        if re.search(r"FROM MEDGUARD\.PATIENT WHERE PATIENT_ID", sql):
            return Result([(1,)])
        if re.search(r"^SELECT CLASS_NAME FROM MEDGUARD\.DRUG_CLASS WHERE", sql):
            return Result([("NSAID",)])
        if sql.lstrip().startswith("WITH candidate_classes"):
            return Result([tuple(row.model_dump().values()) for row in self.rows])
        raise RuntimeError(f"unexpected SQL: {sql[:120]}")

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def close(self):
        self.log.append(("close",))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class RecordingFactory:
    def __init__(self, rows: list[EvidenceRow], error: Exception | None = None) -> None:
        self.rows, self.error = rows, error
        self.calls: list[dict] = []
        self.log: list[tuple] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return RecordingConnection(self.log, self.rows)


def run_main(connect_factory, *, evidence=None):
    out, err = io.StringIO(), io.StringIO()
    code = seed.main(["--verify"], connect_factory=connect_factory, out=out, err=err, target=TARGET,
                     evidence_source=evidence)
    assert SENTINEL not in out.getvalue() + err.getvalue(), "a credential value was printed"
    return code, out.getvalue(), err.getvalue()


# --- Inputs: only the Demo_Fixture (Requirement 13.10) ---


def test_verify_mode_loads_only_the_demo_fixture_and_runs_the_join_for_patient_1_and_ibuprofen(
        inputs, only_fixture):
    db = FakeDb(inputs)
    evidence = FakeEvidence(db, found_rows(inputs))
    code, out, err = run_main(db, evidence=evidence)
    assert code == seed.EXIT_OK, err
    assert evidence.calls == [(1, date(2026, 11, 13), 104, None)]
    # with an injected source it opens no connection of its own
    assert db.calls == [] and db.log == []


@pytest.mark.parametrize("content", ["{ not json", json.dumps({"patient": "nobody"})])
def test_verify_mode_fixture_load_error_exits_3_before_any_connection(tmp_path, monkeypatch, inputs, content):
    broken = tmp_path / "demo_fixture.json"
    broken.write_text(content, encoding="utf-8")
    monkeypatch.setattr(seed, "FIXTURE_PATH", broken)
    db = FakeDb(inputs)
    evidence = FakeEvidence(db, found_rows(inputs))
    code, out, err = run_main(db, evidence=evidence)
    assert code == seed.EXIT_INPUT
    assert "Demo_Fixture" in err
    assert db.calls == [] and evidence.calls == []


def test_verify_mode_missing_fixture_exits_3(tmp_path, monkeypatch, inputs):
    monkeypatch.setattr(seed, "FIXTURE_PATH", tmp_path / "missing.json")
    db = FakeDb(inputs)
    code, out, err = run_main(
        db, evidence=FakeEvidence(db, found_rows(inputs)))
    assert code == seed.EXIT_INPUT and db.calls == []


# --- Report and exit status (Requirements 13.9, 13.10, 13.11) ---


def test_verify_mode_prints_format_report_and_exits_0_on_evidence_found(inputs, only_fixture):
    db = FakeDb(inputs)
    evidence = FakeEvidence(db, found_rows(inputs))
    out, err = io.StringIO(), io.StringIO()
    fixture = seed.load_fixture(seed.FIXTURE_PATH)
    code = seed.verify_mode(fixture, connect_factory=db, out=out, err=err, target=TARGET,
                            evidence_source=evidence)
    assert code == seed.EXIT_OK, err.getvalue()
    from hackathon26.join_verification import verify_join
    expected = verify_join(1, date(2026, 11, 13), candidate_drug_id=104,
                           source=FakeEvidence(db, found_rows(inputs)))
    assert expected.status == "EVIDENCE_FOUND"
    assert format_report(expected) in out.getvalue()


@pytest.mark.parametrize("rows, error, status", [
    ([], None, "NO_DOCUMENTED_INTERACTION_FOUND"),
    (None, UnknownPatient(), "UNKNOWN_PATIENT"),
])
def test_verify_mode_other_status_exits_8(inputs, only_fixture, rows, error, status):
    db = FakeDb(inputs)
    code, out, err = run_main(db, evidence=FakeEvidence(db, rows, error))
    assert code == seed.EXIT_JOIN
    assert status in out
    assert "safe" not in (out + err).lower()


def test_verify_mode_unverified_evidence_exits_8(inputs, only_fixture):
    db = FakeDb(inputs)
    rows = [found_rows(inputs)[0].model_copy(
        update={"evidence_quote": "a quote that is not in the label"})]
    code, out, err = run_main(db, evidence=FakeEvidence(db, rows))
    assert code == seed.EXIT_JOIN
    assert "EVIDENCE_UNVERIFIED" in out


def test_verify_mode_query_failure_is_redacted_and_exits_8(inputs, only_fixture):
    db = FakeDb(inputs)
    error = EvidenceStoreUnavailable(
        "Evidence storage unavailable or incompatible")
    error.__cause__ = RuntimeError(f"socket closed for sys/{SENTINEL}")
    code, out, err = run_main(db, evidence=FakeEvidence(db, error=error))
    assert code == seed.EXIT_JOIN
    assert "QUERY_FAILED" in out and "socket closed" in out and "***" in out


def test_verify_mode_without_ibuprofen_in_the_fixture_reports_a_status_and_exits_8(inputs):
    fixture = seed.load_fixture(seed.FIXTURE_PATH)
    renamed = fixture.model_copy(update={"drugs": tuple(
        d.model_copy(update={"generic_name": "not-ibuprofen"}
                     ) if d.generic_name == "ibuprofen" else d
        for d in fixture.drugs)})
    db = FakeDb(inputs)
    evidence = FakeEvidence(db, found_rows(inputs))
    out, err = io.StringIO(), io.StringIO()
    code = seed.verify_mode(renamed, connect_factory=db, out=out, err=err, target=TARGET,
                            evidence_source=evidence)
    assert code == seed.EXIT_JOIN
    assert "UNKNOWN_CANDIDATE" in out.getvalue() and evidence.calls == []


# --- Read-only on the default source (Requirements 13.10, 15.3, 16.5) ---


def test_verify_mode_runs_only_selects_on_one_autocommit_connection(inputs, only_fixture):
    factory = RecordingFactory(found_rows(inputs))
    code, out, err = run_main(factory)
    assert code == seed.EXIT_OK, err
    assert factory.calls == [
        {"schema": "", "autocommit": True, "connection_timeout": 30}]
    statements = [entry[1] for entry in factory.log if entry[0] == "sql"]
    assert len(statements) == 3
    for sql in statements:
        assert re.match(r"^\s*(SELECT|WITH)\b", sql), sql
        assert not NOT_READ_ONLY_RE.search(sql), sql
        names = re.findall(
            r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", sql, re.IGNORECASE)
        assert all(name.startswith("MEDGUARD.") or name.islower()
                   for name in names), names
    kinds = {entry[0] for entry in factory.log}
    # no insert_multi, COMMIT or ROLLBACK
    assert kinds <= {"sql", "close"}, kinds
    assert "close" in kinds
    assert "EVIDENCE_FOUND" in out


def test_verify_mode_connect_error_exits_4_with_host_port_and_redacted_error(inputs, only_fixture):
    factory = RecordingFactory([], error=RuntimeError(
        f"login failed for sys with password {SENTINEL}"))
    code, out, err = run_main(factory)
    assert code == seed.EXIT_CONNECT
    assert "db.example.test:8563" in err
    assert "login failed" in err and "***" in err
    assert factory.log == []


def test_verify_report_is_redacted(inputs, only_fixture, monkeypatch):
    """A report that somehow carries the password (for example in a label quote) is printed redacted."""
    leaky = JoinVerification("QUERY_FAILED", f"error for sys/{SENTINEL}", None)
    monkeypatch.setattr(
        "hackathon26.join_verification.verify_join", lambda *a, **k: leaky)
    db = FakeDb(inputs)
    code, out, err = run_main(
        db, evidence=FakeEvidence(db, found_rows(inputs)))
    assert code == seed.EXIT_JOIN and "***" in out
