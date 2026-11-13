"""Conservative matching within one patient's active recorded medications."""

import re

from hackathon26.listener.detect import detect_mentions
from hackathon26.listener.models import Mention
from hackathon26.match_level import MatchLevel

from .models import Candidate, MentionResolution, RecordedMedication, ResolutionResult, ResolveRequest


def _normalized(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _candidate(mention: Mention, medicine: RecordedMedication) -> Candidate | None:
    words = set(re.findall(r"\w+", mention.raw_text.lower()))
    if mention.kind == "NAME":
        name = _normalized(medicine.generic_name)
        raw = _normalized(mention.raw_text)
        if name == raw or name.startswith(raw + " "):
            return Candidate(**medicine.model_dump(), match_level=MatchLevel.NAME_MATCH,
                             basis="Name matches an entry on this patient's active recorded list; product unconfirmed.")
        return None
    if mention.kind != "APPEARANCE" or not medicine.appearance_source:
        return None
    if not medicine.strength or _normalized(medicine.strength) != _normalized(medicine.appearance_strength):
        return None
    colors = words & {"white", "yellow", "red", "blue", "pink"}
    shapes = words & {"round", "oval", "oblong"}
    if "long" in words:
        shapes.add("oblong")
    if not colors or _normalized(medicine.color) not in colors:
        return None
    if shapes and _normalized(medicine.shape) not in shapes:
        return None
    return Candidate(**medicine.model_dump(),
                     match_level=MatchLevel.COLOUR_SHAPE_MATCH if shapes else MatchLevel.COLOUR_MATCH,
                     basis="Supported color/shape attributes match a sourced appearance at the recorded strength; dispensed product unverified.")


def _resolve(mention: Mention, medicines: list[RecordedMedication]) -> MentionResolution:
    eligible = mention.subject == "PATIENT" and mention.assertion == "AFFIRMED" and mention.temporal == "CURRENT"
    candidates = []
    if eligible:
        for medicine in medicines:
            candidate = _candidate(mention, medicine)
            if candidate is not None and candidate not in candidates:
                candidates.append(candidate)
    limitations = ["A candidate is not a confirmed medicine; clinician verification is required."]
    if mention.kind == "APPEARANCE":
        limitations.append("Size, score line, imprint and dosage form are not checked; appearances may vary by maker and dispensed product.")
    if not candidates:
        limitations.append("No candidate established from this patient's active recorded list; this does not prove the medicine is absent from other records.")
    if not eligible:
        limitations.append("Current patient exposure is not established by the transcript context.")
    return MentionResolution(
        mention=mention, status="CONTEXT_REVIEW" if not eligible else "CANDIDATES" if candidates else "UNRESOLVED",
        candidates=candidates, limitations=limitations,
        clarification="Clinician: confirm who takes it, current use, and the exact product or packaging before accepting a candidate.",
    )


def resolve_segment(patient_id: int, request: ResolveRequest,
                    medicines: list[RecordedMedication]) -> ResolutionResult:
    analysis = detect_mentions(request.segment)
    resolutions = [_resolve(mention, medicines) for mention in analysis.mentions]
    _flag_linked_conflicts(request.segment.text, resolutions)
    return ResolutionResult(
        patient_id=patient_id, as_of=request.as_of, event_id=analysis.event_id,
        consultation_id=analysis.consultation_id, segment_id=analysis.segment_id,
        revision=analysis.revision, sequence=analysis.sequence, status=analysis.status,
        resolutions=resolutions,
        limitations=[
            "Limited English scripted-transcript rules; unsupported language may be missed or misinterpreted.",
            "Active recorded medication list only; actual use and dispensed manufacturer are unverified.",
            "No labs, label evidence or interactions checked; no clinician decision or audit record saved.",
        ],
    )


def _flag_linked_conflicts(text: str, resolutions: list[MentionResolution]) -> None:
    """Treat adjacent appositive name/appearance descriptions as one hypothesis."""
    for index in range(len(resolutions) - 1):
        first, second = resolutions[index:index + 2]
        if {first.mention.kind, second.mention.kind} != {"NAME", "APPEARANCE"}:
            continue
        gap = text[first.mention.end:second.mention.start]
        if not re.fullmatch(r"\s*,\s*", gap):
            continue
        common = {c.drug_id for c in first.candidates} & {c.drug_id for c in second.candidates}
        if common:
            continue
        for position in (index, index + 1):
            item = resolutions[position]
            resolutions[position] = item.model_copy(update={
                "status": "CONTEXT_REVIEW", "candidates": [],
                "limitations": item.limitations + ["Linked name and appearance conflict or lack shared support; clarify the product before matching."],
            })
