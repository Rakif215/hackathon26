"""Join_Verification adapter: maps evidence results and exceptions to the six Join_Status values.

Uses a fake EvidenceSource and the real verify_rows; no database, no network.
"""

import re
from datetime import date
from decimal import Decimal
from hashlib import sha256

import pytest

from hackathon26.evidence_check.models import EvidenceRequest, EvidenceRow
from hackathon26.evidence_check.repository import EvidenceStoreUnavailable, UnknownCandidate
from hackathon26.join_verification import JoinVerification, format_report, make_redactor, verify_join
from hackathon26.resolution.repository import UnknownPatient

AS_OF = date(2026, 11, 13)
SECTION_TEXT = (
    "7 DRUG INTERACTIONS\n"
    "Coadministration of NSAIDs with ACE inhibitors and diuretics may result in "
    "deterioration of renal function, including possible acute renal failure."
)
QUOTE = "may result in deterioration of renal function, including possible acute renal failure"
TRUST_WORD = re.compile(r"(?<![A-Za-z0-9])(safe|safely|safer|safest|safety)(?![A-Za-z0-9])", re.IGNORECASE)
SENTINEL_PASSWORD = "s3ntinel-Pa55"


class FakeSource:
    """Records every fetch; returns fixed rows or raises a fixed error."""

    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []

    def fetch(self, patient_id, request):
        self.calls.append((patient_id, request))
        if self.error is not None:
            raise self.error
        return self.rows


def row(**overrides) -> EvidenceRow:
    values = dict(
        rule_id=1, rule_name="Triple whammy: renal function", analyte="EGFR", direction="LOW",
        supplying_medications="furosemide, ramipril", section_id=4001, section_type="drug_interactions",
        label_set_id="aaaa-bbbb", label_effective_at=date(2025, 3, 1),
        source_url="https://api.fda.gov/drug/label.json?search=set_id:aaaa-bbbb",
        content_sha256=sha256(SECTION_TEXT.encode()).hexdigest(), section_text=SECTION_TEXT,
        evidence_quote=QUOTE, lab_id=10, value_num=Decimal("48"), unit="mL/min/1.73m2",
        ref_low=Decimal("60"), ref_high=None, measured_at=date(2026, 11, 3),
    )
    values.update(overrides)
    return EvidenceRow(**values)


NULL_LAB = dict(lab_id=None, value_num=None, unit=None, ref_low=None, ref_high=None, measured_at=None)


def run(source, **candidate) -> JoinVerification:
    if not candidate:
        candidate = {"candidate_drug_id": 104}
    return verify_join(1, AS_OF, source=source, **candidate)


# --- candidate parameters (Requirements 12.13, 13.14, 17.12) ---

@pytest.mark.parametrize("candidate", [
    {"candidate_drug_id": 104, "candidate_class_name": "NSAID"},
    {"candidate_drug_id": None, "candidate_class_name": None},
])
def test_both_or_neither_candidate_is_unknown_candidate_without_fetch(candidate):
    source = FakeSource()
    result = verify_join(1, AS_OF, source=source, **candidate)
    assert result.status == "UNKNOWN_CANDIDATE"
    assert "candidate_drug_id" in result.detail and "candidate_class_name" in result.detail
    assert result.result is None
    assert source.calls == []


def test_blank_class_name_is_unknown_candidate_without_fetch():
    source = FakeSource()
    result = run(source, candidate_class_name="   ")
    assert result.status == "UNKNOWN_CANDIDATE"
    assert source.calls == []


# --- exceptions from the source (Requirements 12.14, 13.6, 13.7, 13.14) ---

def test_unknown_patient():
    result = verify_join(999, AS_OF, candidate_drug_id=104, source=FakeSource(error=UnknownPatient()))
    assert result.status == "UNKNOWN_PATIENT"
    assert "999" in result.detail
    assert result.result is None


@pytest.mark.parametrize(("candidate", "named"), [
    ({"candidate_drug_id": 777}, "777"),
    ({"candidate_class_name": "nsaid"}, "'nsaid'"),
])
def test_unknown_candidate_names_the_candidate(candidate, named):
    result = run(FakeSource(error=UnknownCandidate()), **candidate)
    assert result.status == "UNKNOWN_CANDIDATE"
    assert named in result.detail
    assert "no documented interaction found" not in result.detail


def test_query_failed_carries_redacted_database_message():
    error = EvidenceStoreUnavailable("Evidence storage unavailable or incompatible")
    error.__cause__ = OSError(f"connection refused for sys/{SENTINEL_PASSWORD} at 127.0.0.1:8563")
    result = verify_join(1, AS_OF, candidate_drug_id=104, source=FakeSource(error=error),
                         redact=make_redactor(SENTINEL_PASSWORD))
    assert result.status == "QUERY_FAILED"
    assert "connection refused" in result.detail and "127.0.0.1:8563" in result.detail
    assert SENTINEL_PASSWORD not in result.detail
    assert SENTINEL_PASSWORD not in format_report(result)


def test_query_failed_without_cause_uses_exception_text():
    result = run(FakeSource(error=EvidenceStoreUnavailable("Evidence storage unavailable or incompatible")))
    assert result.status == "QUERY_FAILED"
    assert "Evidence storage unavailable" in result.detail


def test_make_redactor_ignores_empty_secrets():
    redact = make_redactor("", None, "abc")
    assert redact("x abc y abc") == "x *** y ***"
    assert make_redactor()("unchanged") == "unchanged"


# --- rows through the real verify_rows (Requirements 13.1-13.5, 13.13, 17.12) ---

def test_request_reaches_the_source():
    source = FakeSource([row()])
    run(source, candidate_class_name="NSAID")
    assert source.calls == [(1, EvidenceRequest(as_of=AS_OF, candidate_class_name="NSAID"))]


def test_bad_quote_is_unverified_naming_rule_and_section():
    result = run(FakeSource([row(), row(lab_id=11, evidence_quote="renal function is unaffected")]))
    assert result.status == "EVIDENCE_UNVERIFIED"
    assert result.result.findings == []
    report = format_report(result)
    assert "Triple whammy: renal function" in report and "4001" in report and "quote" in report


@pytest.mark.parametrize("bad", [{"content_sha256": "0" * 64}, {"content_sha256": None}])
def test_bad_hash_is_unverified(bad):
    result = run(FakeSource([row(**bad)]))
    assert result.status == "EVIDENCE_UNVERIFIED"
    assert any("Triple whammy: renal function" in f and "4001" in f and "hash" in f
               for f in result.result.failures)


@pytest.mark.parametrize("missing", ["evidence_quote", "section_text"])
def test_null_quote_or_section_text_is_unverified(missing):
    assert run(FakeSource([row(**{missing: None})])).status == "EVIDENCE_UNVERIFIED"


def test_zero_rows_is_no_documented_interaction_found():
    result = run(FakeSource([]))
    assert result.status == "NO_DOCUMENTED_INTERACTION_FOUND"
    assert result.detail == "no documented interaction found"
    report = format_report(result)
    assert "no documented interaction found" in report
    assert TRUST_WORD.search(report) is None


def test_null_lab_columns_give_empty_lab_list_and_limitation():
    result = run(FakeSource([row(**NULL_LAB)]))
    assert result.status == "EVIDENCE_FOUND"
    [finding] = result.result.findings
    assert finding.labs == []
    assert "no EGFR result in the 365 days up to 2026-11-13" in finding.limitations
    assert "no EGFR result in the 365 days up to 2026-11-13" in format_report(result)


def test_reference_range_flag_at_join_verification_output():
    # Design gap 1: the flag is computed in verify_rows, not returned by the query. Tested here.
    rows = [row(lab_id=1, value_num=Decimal("62"), measured_at=date(2026, 5, 1)),
            row(lab_id=2, value_num=Decimal("60"), measured_at=date(2026, 8, 1)),
            row(lab_id=3, value_num=Decimal("48"), measured_at=date(2026, 11, 3)),
            row(lab_id=4, value_num=Decimal("99"), ref_low=None, measured_at=date(2026, 11, 4))]
    [finding] = run(FakeSource(rows)).result.findings
    assert [lab.outside_reference_range for lab in finding.labs] == [False, False, True, False]


# --- format_report (Requirements 13.3, 14.3) ---

def test_format_report_for_evidence_found():
    rows = [row(lab_id=1, value_num=Decimal("62"), measured_at=date(2026, 5, 1)),
            row(lab_id=2, value_num=Decimal("48"), measured_at=date(2026, 11, 3))]
    result = run(FakeSource(rows))
    assert result.status == "EVIDENCE_FOUND"
    report = format_report(result)
    for expected in ("EVIDENCE_FOUND", "Triple whammy: renal function", "EGFR", "LOW", QUOTE,
                     "4001", "aaaa-bbbb", "2025-03-01", "furosemide, ramipril",
                     "62 mL/min/1.73m2 on 2026-05-01, outside reference range: no",
                     "48 mL/min/1.73m2 on 2026-11-03, outside reference range: yes"):
        assert expected in report, expected
    assert TRUST_WORD.search(report) is None


def test_format_report_names_absent_suppliers():
    report = format_report(run(FakeSource([row(supplying_medications=None)])))
    assert "Supplying current medications: none" in report


@pytest.mark.parametrize("error", [UnknownPatient(), UnknownCandidate(), EvidenceStoreUnavailable("down")])
def test_format_report_for_exception_statuses_has_status_and_no_trust_word(error):
    result = run(FakeSource(error=error))
    report = format_report(result)
    assert report.startswith(result.status) and result.detail in report
    assert TRUST_WORD.search(report) is None


# --- differences between verify_rows and the requirements (design gap 4) ---

@pytest.mark.xfail(strict=True, reason=(
    "Design gap 4: verify_rows also rejects a non-https SOURCE_URL or a lab outside the date window. "
    "Requirement 13.3 asks for EVIDENCE_FOUND whenever the quote and hash checks pass. "
    "Owned by evidence_check; not edited here."))
@pytest.mark.parametrize("stricter", [
    {"source_url": "http://api.fda.gov/drug/label.json"},
    {"measured_at": date(2025, 1, 1)},
])
def test_quote_and_hash_pass_gives_evidence_found(stricter):
    assert run(FakeSource([row(**stricter)])).status == "EVIDENCE_FOUND"
