# Listener foundation

The first MedGuard service analyzes finalized synthetic English transcript segments. It returns unconfirmed medicine-name, appearance and indication mentions, original text spans, heuristic context, clarification prompts and coverage limitations. It does not identify a patient's pill, check an interaction, provide advice, call Bedrock, or write database/audit records.

Start from the repository root:

```sh
uv run uvicorn hackathon26.api:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

Interactive API docs: http://127.0.0.1:8000/docs

```sh
curl -sS http://127.0.0.1:8000/api/v1/listener/analyze \
  -H 'Content-Type: application/json' \
  --data-binary @data/demo/listener-segment.json
```

The example produces an APPEARANCE mention and an INDICATION mention; it does not infer a drug from knee pain. Every result includes `persisted: false`. `GET /health/live` checks only process health, not Exasol/AWS readiness.

The envelope requires version, event/consultation/segment IDs, positive integer revision/sequence, speaker (`PATIENT`, `DOCTOR`, `UNKNOWN`), text (1–4000 characters, not blank), a boolean `is_final`, `source: script`, and a timezone-aware timestamp. Unknown fields are rejected. Input text is preserved exactly. Spans use half-open Python Unicode character offsets; JavaScript consumers must account for UTF-16 representation when emoji or supplementary characters precede a mention.

Partial segments return `PROVISIONAL` with no extracted mentions. Finalized segments return `ANALYZED`; this means the limited detector ran, not that a medication was confirmed or all mentions were found. Doctor/unknown speaker statements are not promoted to patient exposure. Context interpretation is heuristic and requires clinician verification, particularly compound statements, reported speech and unfamiliar phrasing. Match confidence is a descriptive basis, not a calibrated probability.

Direct Lambda entry point: `hackathon26.listener.lambda_handler.handler`. Its event is the segment JSON itself, not API Gateway/SQS envelopes. Invalid events raise Pydantic validation errors and fail the invocation. The adapter can be exercised locally:

```sh
PYTHONPATH=src uv run python - <<'PY'
import json
from pathlib import Path
from hackathon26.listener.lambda_handler import handler
event = json.loads(Path('data/demo/listener-segment.json').read_text())
print(json.dumps(handler(event, None), indent=2))
PY
```

No Lambda resources are deployed by this change. No credentials are needed to run this module. Before cloud integration, add durable processing/idempotency and sequence/revision handling, resolve execution-role configuration, verify Exasol network access, and implement queue retries/DLQ handling. Repeated stateless analysis is deterministic but is not a durable exactly-once processing guarantee.

Run all tests: `uv run pytest -q`.

Detailed next steps: [listener/serverless design](superpowers/plans/2026-11-13-listener-serverless-design.md).

## Patient-specific candidate resolution

`POST /api/v1/patients/{patient_id}/listener/resolve` now accepts:

```json
{
  "as_of": "2026-11-13",
  "segment": {
    "schema_version": "1", "event_id": "demo-event-1",
    "consultation_id": "demo-consultation-1", "segment_id": "segment-1",
    "revision": 1, "sequence": 1, "speaker": "PATIENT",
    "text": "I take the long white one.", "is_final": true,
    "source": "script", "occurred_at": "2026-11-13T10:00:00Z"
  }
}
```

Use a positive numeric synthetic patient ID from the canonical database. This endpoint reads Exasol through the existing credential helper; it does not substitute a fixture if the database is missing or incompatible. It returns 404 for an absent/non-synthetic patient, 503 for unavailable/incompatible medication storage, and 422 for invalid input. Canonical data-foundation setup is a prerequisite.

Candidates include the patient medication row, drug ID, recorded strength, manufacturer/appearance source and named `NAME_MATCH`, `COLOUR_MATCH` or `COLOUR_SHAPE_MATCH` level. “White” may return several candidates. Supported shape constraints narrow them. Unknown size, imprint, dosage form and manufacturer remain limitations; no probability or actual dispensed-product verification is implied. Appearance matching requires a sourced appearance at the same recorded strength (conservative text equality; equivalent strength spellings may remain unmatched).

Only affirmed, current, patient-attributed mentions receive candidates. Other contexts return `CONTEXT_REVIEW`. An indication alone stays unresolved; a named medicine outside the active list also remains unresolved. None of these states establishes safety, actual use or a clinician decision. These read-only results remain `persisted: false`.

The agreed synthetic patient has white round ramipril, yellow oval metoprolol succinate, and white oblong furosemide. “Long” maps to the supported shape “oblong”; the original mention text and offsets are preserved. Unqualified “white” can still refer to ramipril or furosemide.

The supplied consultation ID is correlation metadata only: this stateless endpoint does not yet validate a persisted consultation-to-patient binding. Keep it loopback-only for synthetic development; session binding, authentication and durable review are later integration work.
