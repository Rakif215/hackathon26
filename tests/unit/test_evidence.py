from datetime import date
from hashlib import sha256

import pytest
from pydantic import ValidationError

from hackathon26.evidence import verify_quote
from hackathon26.evidence_check.models import EvidenceRequest, EvidenceRow
from hackathon26.evidence_check.verify import verify_rows


@pytest.mark.parametrize("quote,text,expected", [
    ("renal function", "May affect renal function.", True),
    (None, "text", False), ("", "text", False), ("\u2003\t", "text", False),
    ("text", None, False), ("Text", "text", False),
    ("a b", "a\nb", False), ("’", "'", False), (" renal", "renal", False),
    ("é", "e\u0301", False), ("💊", "a💊b", True),
])
def test_quote_verifier_uses_exact_characters(quote, text, expected):
    assert verify_quote(quote, text) is expected


def row(**updates):
    text = "Synthetic test evidence: example risk statement."
    return EvidenceRow.model_validate({
        "rule_id": 1, "rule_name": "synthetic rule", "analyte": "EGFR", "direction": "LOW",
        "supplying_medications": "ramipril, furosemide", "section_id": 10,
        "section_type": "drug_interactions", "label_set_id": "test-label",
        "label_effective_at": "2022-07-01", "source_url": "https://api.fda.gov/drug/label.json",
        "content_sha256": sha256(text.encode()).hexdigest(), "section_text": text,
        "evidence_quote": "example risk statement.", "lab_id": 20, "value_num": "48",
        "unit": "mL/min/1.73m2", "ref_low": "60", "ref_high": None,
        "measured_at": "2026-11-01",
    } | updates)


def test_verified_result_has_source_quote_and_dated_labs():
    result = verify_rows(1, EvidenceRequest(as_of=date(2026, 11, 13), candidate_drug_id=4), [row()])
    assert result.status == "EVIDENCE_FOUND"
    finding = result.findings[0]
    assert finding.evidence_quote == "example risk statement."
    assert finding.section_id == 10
    assert finding.labs[0].outside_reference_range is True
    assert finding.needs_review is True
    assert result.persisted is False


@pytest.mark.parametrize("updates", [
    {"evidence_quote": "invented"}, {"content_sha256": "0" * 64}, {"section_text": None},
    {"source_url": None}, {"label_set_id": None}, {"section_id": None},
    {"source_url": "https://["}, {"section_type": " "}, {"label_set_id": "\t"},
])
def test_unverified_row_blocks_all_findings(updates):
    result = verify_rows(1, EvidenceRequest(as_of=date(2026, 11, 13), candidate_drug_id=4), [row(), row(**updates)])
    assert result.status == "EVIDENCE_UNVERIFIED"
    assert result.findings == []
    assert result.failures


def test_missing_labs_do_not_hide_an_evidence_match():
    result = verify_rows(1, EvidenceRequest(as_of=date(2026, 11, 13), candidate_drug_id=4), [
        row(lab_id=None, value_num=None, unit=None, measured_at=None, ref_low=None)
    ])
    assert result.status == "EVIDENCE_FOUND"
    assert result.findings[0].labs == []
    assert "no EGFR result in the 365 days up to 2026-11-13" in result.findings[0].limitations


def test_no_hit_is_not_an_assertion_of_safety():
    result = verify_rows(1, EvidenceRequest(as_of=date(2026, 11, 13), candidate_class_name="NSAID"), [])
    assert result.status == "NO_DOCUMENTED_INTERACTION_FOUND"
    assert result.message == "no documented interaction found"


@pytest.mark.parametrize("kwargs", [{}, {"candidate_drug_id": 1, "candidate_class_name": "NSAID"},
                                    {"candidate_drug_id": 0}, {"candidate_class_name": " "}])
def test_candidate_must_be_exactly_one_valid_identifier(kwargs):
    with pytest.raises(ValidationError):
        EvidenceRequest(as_of=date(2026, 11, 13), **kwargs)
