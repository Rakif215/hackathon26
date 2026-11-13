"""Model output can select evidence, never introduce clinical assertions."""

import json

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from hackathon26.evidence_check.models import EvidenceResult

from .models import EvidenceModel, ModelSelection, Summary, SynthesisResult


class GuardrailNotConfigured(RuntimeError):
    """A numbered Guardrail configuration is required; no unguarded fallback."""


def _validated_summaries(text: str, evidence: EvidenceResult) -> list[Summary]:
    if len(text) > 64_000:
        raise ValueError("Output exceeds allowed size")
    selection = ModelSelection.model_validate_json(text)
    by_rule = {finding.rule_id: finding for finding in evidence.findings}
    ids = [item.rule_id for item in selection.items]
    if len(ids) != len(set(ids)) or set(ids) != set(by_rule):
        raise ValueError("Every evidence rule must occur exactly once")
    summaries = []
    for item in selection.items:
        finding = by_rule[item.rule_id]
        expected_labs = {lab.lab_id for lab in finding.labs}
        if (item.section_id != finding.section_id or item.quote != finding.evidence_quote
                or len(item.lab_ids) != len(set(item.lab_ids)) or set(item.lab_ids) != expected_labs):
            raise ValueError("Quote, section and complete lab references must match verified evidence")
        summaries.append(Summary(**item.model_dump()))
    return summaries


def summarize(evidence: EvidenceResult, model: EvidenceModel) -> SynthesisResult:
    def result(status, guardrail_status, message, summaries=None, model_id=None):
        return SynthesisResult(status=status, guardrail_status=guardrail_status, message=message,
                               evidence=evidence, summaries=summaries or [], model_id=model_id)

    if evidence.status != "EVIDENCE_FOUND" or not evidence.findings:
        return result("NOT_REQUESTED", "NOT_REQUESTED", "No verified evidence packet available for synthesis.")
    packet = json.dumps({"findings": [finding.model_dump(mode="json") for finding in evidence.findings]},
                        ensure_ascii=False, separators=(",", ":"))
    if len(packet) > 48_000:
        return result("UNAVAILABLE", "NOT_REQUESTED", "Evidence packet exceeds this worker's bounded input size.")
    try:
        reply = model.generate(packet)
    except GuardrailNotConfigured:
        return result("UNAVAILABLE", "NOT_CONFIGURED", "Synthesis unavailable: a numbered Guardrail configuration is required.")
    except (BotoCoreError, ClientError, OSError, RuntimeError):
        return result("UNAVAILABLE", "UNCONFIRMED", "Synthesis unavailable; verified evidence remains available for clinician review.")
    if reply.stop_reason == "guardrail_intervened":
        return result("BLOCKED", "INTERVENED", "Guardrail intervened; model output was not published.", model_id=reply.model_id)
    if not reply.guardrail_assessed or reply.stop_reason != "end_turn":
        return result("INVALID_OUTPUT", "UNCONFIRMED" if not reply.guardrail_assessed else "ASSESSED",
                      "Completed guarded synthesis could not be confirmed; model output was not published.", model_id=reply.model_id)
    try:
        summaries = _validated_summaries(reply.text, evidence)
    except (ValidationError, ValueError):
        return result("INVALID_OUTPUT", "ASSESSED", "Model references did not match the complete verified evidence packet.", model_id=reply.model_id)
    return result("GENERATED", "ASSESSED", "Exact evidence selections validated for clinician review.", summaries, reply.model_id)
