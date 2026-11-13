# Consultation replay API

These routes use the seeded consultation and utterances as a read-only script. Each replay stores only its start event and progress in the app-owned AUDIT_LOG. They do not create, replace or edit CONSULTATION, UTTERANCE or patient medication rows.

## Start or resume

POST `/api/v1/consultations/1/replays`:

```json
{"idempotency_key":"demo-start-001"}
```

Keep the returned numeric `replay_id`. Repeat the same start key to resume the same replay, even after an API restart. A different key creates an independent replay. GET `/api/v1/consultations/1/replays/{replay_id}` restores its current snapshot without advancing.

## Advance

POST `/api/v1/consultations/1/replays/{replay_id}/advance`:

```json
{"idempotency_key":"demo-next-001","expected_sequence":0}
```

The first advance expects sequence zero and reveals utterance one. For each new step, use a new key and the sequence in the last snapshot. Retrying an identical key/body does not advance again; it returns the current snapshot, which may include later steps already committed. A stale sequence, key reused for a different step, changed script or ID collision returns 409. Advancing a completed replay also returns 409. There is no automatic acceptance of suggestions or clinician decisions.

Snapshots contain consultation/patient/replay IDs, creation time, READY/PLAYING/COMPLETED status, sequence, total_utterances, visible utterances, last_segment and last_analysis. `progress_persisted: true` refers only to replay audit events. Listener analysis is recomputed from the pinned script using the current detector, is explicitly unpersisted, and may change when detector code changes. Use last_segment with the existing patient resolution endpoint when explicit candidate resolution is needed; subsequent evidence, synthesis and review commands remain separate.

The script hash covers patient association, consultation metadata and the ordered utterance IDs/text/speakers/timing. A changed seed cannot silently reinterpret an existing replay: start a new replay key after a deliberate script update. Existing audit history is never deleted by these routes.

The current schema has no replay table or revision column. Each next-step event uses a deterministic audit ID shared by competing commands for that step; the audit primary key prevents duplicate progress. Full stored event content is compared on recovery; hash collisions fail closed. IDs fit DECIMAL(10,0). Real Exasol concurrency and recovery behavior still need verification once canonical setup is ready.

Only synthetic-patient consultations are served. Unknown consultation/replay or a replay under the wrong consultation returns 404; incompatible/missing storage returns 503. Scripts must have unique contiguous sequences starting at one and valid speakers/text/timing. Naive seeded timestamps are interpreted as UTC for synthetic replay; offset_ms supplies segment times. No microphone or wall-clock streaming is involved.

No authorization/session-login system is included. Keep the API on loopback for synthetic development. The old six-table database will return 503; no attempt was made to replace it.

Focused tests: `uv run pytest tests/unit/test_replay.py tests/api/test_replay_api.py -q`.
