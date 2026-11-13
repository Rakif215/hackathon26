"""Join_Verification: map the existing evidence check onto the six Join_Status values.

A pure adapter over ``evidence_check``. It adds no query and no second quote verifier: the
``EvidenceSource`` runs the Evidence_Join_Query and ``verify_rows`` checks quotes and hashes.
``verify_join`` returns exactly one status and never exits; the caller owns the exit code.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import ValidationError

from hackathon26.evidence_check.models import EvidenceRequest, EvidenceResult
from hackathon26.evidence_check.repository import EvidenceSource, EvidenceStoreUnavailable, UnknownCandidate
from hackathon26.evidence_check.verify import verify_rows
from hackathon26.resolution.repository import UnknownPatient

JoinStatus = Literal["EVIDENCE_FOUND", "NO_DOCUMENTED_INTERACTION_FOUND", "EVIDENCE_UNVERIFIED",
                     "UNKNOWN_PATIENT", "UNKNOWN_CANDIDATE", "QUERY_FAILED"]


@dataclass(frozen=True)
class JoinVerification:
    status: JoinStatus
    detail: str
    result: EvidenceResult | None = None


def make_redactor(*secrets: str | None) -> Callable[[str], str]:
    """Return a function that replaces every non-empty secret with ``***``.

    The caller passes the values to hide (for example ``db.settings()["password"]``); this module never
    resolves credentials itself.
    """
    hidden = sorted({secret for secret in secrets if secret},
                    key=len, reverse=True)

    def redact(text: str) -> str:
        for secret in hidden:
            text = text.replace(secret, "***")
        return text

    return redact


def _candidate(drug_id: int | None, class_name: str | None) -> str:
    if drug_id is not None:
        return f"candidate_drug_id {drug_id}"
    return f"candidate_class_name {class_name!r}"


def verify_join(patient_id: int, as_of: date, *, candidate_drug_id: int | None = None,
                candidate_class_name: str | None = None, source: EvidenceSource,
                redact: Callable[[str], str] = str) -> JoinVerification:
    try:
        request = EvidenceRequest(as_of=as_of, candidate_drug_id=candidate_drug_id,
                                  candidate_class_name=candidate_class_name)
    except ValidationError as error:
        reasons = "; ".join(item["msg"] for item in error.errors())
        return JoinVerification(
            "UNKNOWN_CANDIDATE",
            "supply exactly one of candidate_drug_id and candidate_class_name "
            f"(got candidate_drug_id={candidate_drug_id!r}, candidate_class_name={candidate_class_name!r}): "
            f"{reasons}",
        )
    try:
        rows = source.fetch(patient_id, request)
    except UnknownPatient:
        return JoinVerification("UNKNOWN_PATIENT", f"no synthetic PATIENT row for patient id {patient_id}")
    except UnknownCandidate:
        if candidate_drug_id is not None:
            detail = f"{_candidate(candidate_drug_id, None)} has no DRUG_CLASS row"
        else:
            detail = (f"{_candidate(None, candidate_class_name)} equals no DRUG_CLASS CLASS_NAME "
                      "(exact, case-sensitive match)")
        return JoinVerification("UNKNOWN_CANDIDATE", detail)
    except EvidenceStoreUnavailable as error:
        # The repository keeps the database error only in __cause__ (design gap 3).
        cause = error.__cause__ if error.__cause__ is not None else error
        return JoinVerification("QUERY_FAILED", f"query failed: {redact(str(cause))}")
    result = verify_rows(patient_id, request, rows)
    return JoinVerification(result.status, result.message, result)


def _found_lines(result: EvidenceResult) -> list[str]:
    lines = []
    for finding in result.findings:
        effective = finding.label_effective_at.isoformat(
        ) if finding.label_effective_at else "unavailable"
        lines += [
            f"Rule: {finding.rule_name} (analyte {finding.analyte}, direction {finding.direction})",
            f'  Quote: "{finding.evidence_quote}"',
            f"  Source: SECTION_ID {finding.section_id} ({finding.section_type}), "
            f"LABEL_SET_ID {finding.label_set_id}, LABEL_EFFECTIVE_AT {effective}, {finding.source_url}",
            f"  Supplying current medications: {finding.supplying_medications or 'none'}",
        ]
        if finding.labs:
            lines.append("  Labs:")
            lines += [f"    {lab.value} {lab.unit or '(no unit)'} on {lab.measured_at.isoformat()}, "
                      f"outside reference range: {'yes' if lab.outside_reference_range else 'no'}"
                      for lab in finding.labs]
        else:
            lines.append("  Labs: none returned")
        lines.append("  Limitations:")
        lines += [f"    - {limitation}" for limitation in finding.limitations]
    return lines


def format_report(v: JoinVerification) -> str:
    lines = [v.status, v.detail]
    if v.result is not None:
        if v.status == "EVIDENCE_FOUND":
            lines += _found_lines(v.result)
        elif v.status == "EVIDENCE_UNVERIFIED":
            lines.append("Failed checks:")
            lines += [f"  - {failure}" for failure in v.result.failures]
        lines.append("Limitations:")
        lines += [f"  - {limitation}" for limitation in v.result.limitations]
    lines.append("Clinician review required.")
    return "\n".join(lines)
