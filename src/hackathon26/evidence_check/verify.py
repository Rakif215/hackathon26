"""Publish only evidence whose exact quotation and content hash both verify."""

from datetime import timedelta
from hashlib import sha256
from urllib.parse import urlparse

from hackathon26.evidence import verify_quote

from .models import EvidenceFinding, EvidenceRequest, EvidenceResult, EvidenceRow, LabObservation


def _failures(row: EvidenceRow, request: EvidenceRequest) -> list[str]:
    failures = []
    if not verify_quote(row.evidence_quote, row.section_text):
        failures.append("quote")
    if row.section_text is None or sha256(row.section_text.encode()).hexdigest() != row.content_sha256:
        failures.append("hash")
    try:
        url = urlparse(row.source_url or "")
        valid_url = url.scheme == "https" and bool(url.hostname)
    except ValueError:
        valid_url = False
    if not row.section_id or not (row.section_type or "").strip() or not (row.label_set_id or "").strip() or not valid_url:
        failures.append("source metadata")
    if row.label_effective_at is not None and row.label_effective_at > request.as_of:
        failures.append("label effective date is after requested date")
    if row.lab_id is not None:
        if row.value_num is None or row.measured_at is None:
            failures.append("incomplete lab")
        elif not request.as_of - timedelta(days=365) <= row.measured_at <= request.as_of:
            failures.append("lab outside requested date window")
    elif any(value is not None for value in (row.value_num, row.unit, row.measured_at, row.ref_low, row.ref_high)):
        failures.append("lab without identity")
    return [f"{row.rule_name} section {row.section_id}: {check}" for check in failures]


def _finding(rows: list[EvidenceRow], request: EvidenceRequest) -> EvidenceFinding:
    first = rows[0]
    labs = []
    limitations = ["Candidate/class check only; actual exposure, diagnosis and clinical severity are not established."]
    for row in rows:
        if row.lab_id is None:
            continue
        flag = ((row.ref_low is not None and row.value_num < row.ref_low)
                or (row.ref_high is not None and row.value_num > row.ref_high))
        observation = LabObservation(lab_id=row.lab_id, value=row.value_num, unit=row.unit,
                                     measured_at=row.measured_at, outside_reference_range=flag)
        if observation not in labs:
            labs.append(observation)
    labs.sort(key=lambda lab: (lab.measured_at, lab.lab_id))
    if not labs:
        limitations.append(f"no {first.analyte} result in the 365 days up to {request.as_of}")
    if labs and any(lab.unit is None or not lab.unit.strip() for lab in labs):
        limitations.append("Lab units are missing; values cannot be compared as a trend.")
    if len({lab.unit for lab in labs}) > 1:
        limitations.append("Lab units differ; no normalized trend has been calculated.")
    if labs and (request.as_of - labs[-1].measured_at).days > 90:
        limitations.append("Latest retrieved lab is over 90 days old; freshness requires clinician review (demo display rule).")
    if first.label_effective_at is None:
        limitations.append("Label effective date unavailable.")
    return EvidenceFinding(
        **{name: getattr(first, name) for name in (
            "rule_id", "rule_name", "analyte", "direction", "supplying_medications", "section_id",
            "section_type", "label_set_id", "label_effective_at", "source_url", "content_sha256", "evidence_quote",
        )}, labs=labs, limitations=limitations,
    )


def verify_rows(patient_id: int, request: EvidenceRequest, rows: list[EvidenceRow]) -> EvidenceResult:
    failures = [failure for row in rows for failure in _failures(row, request)]
    groups: dict[int, list[EvidenceRow]] = {}
    for row in rows:
        group = groups.setdefault(row.rule_id, [])
        if group and row.model_dump(exclude={"lab_id", "value_num", "unit", "ref_low", "ref_high", "measured_at"}) != group[0].model_dump(exclude={"lab_id", "value_num", "unit", "ref_low", "ref_high", "measured_at"}):
            failures.append(f"{row.rule_name} section {row.section_id}: inconsistent evidence for rule")
        group.append(row)
    status = "EVIDENCE_UNVERIFIED" if failures else "EVIDENCE_FOUND" if rows else "NO_DOCUMENTED_INTERACTION_FOUND"
    return EvidenceResult(
        patient_id=patient_id, request=request, status=status,
        message={"EVIDENCE_UNVERIFIED": "Evidence could not be verified; clinician review required",
                 "EVIDENCE_FOUND": "Verified source evidence found for clinician review",
                 "NO_DOCUMENTED_INTERACTION_FOUND": "no documented interaction found"}[status],
        findings=[] if failures else [_finding(group, request) for _, group in sorted(groups.items())],
        failures=failures, limitations=[
            "Coverage is limited to stored curated rules and labels; an absent match does not establish compatibility.",
            "Reference-range flags use stored lab bounds, not diagnostic or treatment thresholds.",
            "Patient medication use and candidate identity require clinician verification; nothing is saved or automatically changed.",
        ],
    )
