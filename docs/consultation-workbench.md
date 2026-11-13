# Consultation workbench API

One frontend-oriented endpoint coordinates the existing read-only services:

`POST /api/v1/consultations/{consultation_id}/replays/{replay_id}/workbench`

## Analyze the displayed turn

```json
{"expected_sequence":2}
```

The server loads the replay and uses its patient, current segment and script timestamp. It returns the replay snapshot, active recorded medications and mention resolutions. It does not infer a painkiller identity or automatically run risk checks from a vague description.

## Explicit candidate check

```json
{"expected_sequence":2,"candidate_drug_id":4}
```

Use an actual drug ID from the reference data; the example value is not an instruction to select a particular product. This is an explicit hypothetical candidate check, not a medication confirmation, prescription or claim of exposure. A candidate outside the recorded list, such as an unrecorded painkiller, can be checked deliberately.

To additionally request guarded extractive synthesis:

```json
{"expected_sequence":2,"candidate_drug_id":4,"include_synthesis":true}
```

Evidence is always fetched and verified server-side. Synthesis is off by default, requires an explicit candidate, and does not call the model for no-hit or unverified evidence. A repeat request with synthesis enabled may make another paid model call; durable model-job deduplication is not yet implemented.

A label effective after the scripted check date is withheld as unverified. An absent effective date remains an explicit source limitation. A malformed provider response does not discard completed resolution/evidence stages; it produces a partial result with synthesis marked invalid.

## Result handling

| Workbench status | Frontend behavior |
|---|---|
| READY | No utterance revealed; offer Advance. No downstream dependencies called. |
| COMPLETE | Requested stages completed. Inspect their individual statuses; this does not establish compatibility or actual use. |
| PARTIAL | Render available results and each structured problem; do not turn an unavailable stage into an empty/no-hit result. |

`medications: null` means not requested or unavailable; an empty list means the repository returned no active recorded medications. The resolution/evidence/synthesis fields independently retain their results or null. `problems` names the affected stage, error code, message and whether retry is appropriate. Guardrail interventions and invalid output are visible, not silently replaced with generated text.

Unknown replay is 404, invalid/unknown candidate 422, stale/changed replay 409 and unavailable replay storage 503. The cursor is rechecked after processing to reject results when someone advances concurrently. Patient identity and the last segment are also compared. Frontends should still discard responses for a replay/sequence no longer displayed.

The request does not accept patient IDs, caller-authored transcripts, dates or purported verified findings. `as_of` for resolution/evidence is derived from the current segment's scripted date. Patient records are read in separate repository calls, not one atomic cross-service snapshot.

This operation never advances replay, writes FINDING rows, confirms medicine identity, saves clinician review or changes medication records. Its top-level `persisted` is false; the nested replay's progress_persisted flag refers only to existing replay progress. Persisted finding creation is still needed before attaching clinician decisions to these evidence results.

No authentication is included. Keep this synthetic-development API on loopback. Canonical database setup remains required; the old six-table database cannot supply a working replay/workbench. No data/schema changes or live calls were made for this coordinator.

## Frontend sequence

1. Start/resume a replay and display its snapshot.
2. Advance with a new request key and the current sequence.
3. Call the workbench with the returned sequence to display medicines and candidate resolution.
4. On an explicit Check action, send the selected candidate; opt into synthesis separately.
5. Show evidence, uncertainty and problems. Do not label unpersisted results as saved findings.

Focused tests: `uv run pytest tests/unit/test_workbench.py tests/api/test_workbench_api.py tests/unit/test_resolution.py tests/api/test_resolution_api.py -q`.
