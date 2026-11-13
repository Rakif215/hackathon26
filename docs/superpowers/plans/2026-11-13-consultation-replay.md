# Consultation Replay Implementation Plan

> Use Superpowers TDD and focused tests. No schema/data-foundation changes, live writes, staging or commits.

**Goal:** Start, resume and advance a scripted consultation through a durable replay cursor, with no implicit clinician actions.

**Architecture:** Read seeded CONSULTATION/UTTERANCE rows and synthetic patient binding. Store bounded REPLAY_STARTED/REPLAY_STEP events in existing AUDIT_LOG only. Replay ID equals its deterministic start-event ID (DECIMAL10); advance event ID derives from replay and next sequence. Full payload fingerprints detect collisions/key misuse. Primary-key uniqueness serializes competing commands for the same step. Pin a script hash to avoid silently replaying changed seed text.

**Endpoints:** POST `/api/v1/consultations/{id}/replays`, GET `/api/v1/consultations/{id}/replays/{replay_id}`, POST same path plus `/advance`. Start takes idempotency_key; advance takes idempotency_key and expected_sequence (zero before the first utterance).

**Snapshot:** Patient/consultation/replay IDs, replay cursor, total steps, status, visible utterances, last TranscriptSegment and stateless listener analysis. Resolution/evidence/synthesis/review remain explicit existing endpoints; replay never accepts a finding or changes medicine state.

## Tasks

1. Write failing tests for start/retry/resume, advance/retry/key conflict, stale cursor, wrong consultation, script mutation, completion, event collision and failed writes.
2. Implement strict replay models and canonical repository with non-autocommit transactions. Validate contiguous script sequence, bounded event payloads and synthetic patient association.
3. Add API tests and injected adapter, test only relevant replay/listener/API boundaries, and get independent review.
4. Document UTC convention for synthetic naive timestamps, durability versus recomputed analysis, and canonical-setup dependency. Do not claim live Exasol transaction verification before tonight's canonical data is ready.

## Review focus

Concurrent identical/different next commands, gaps/duplicate progress events, cross-consultation state, partial commits, changed script and fake saved acknowledgements. No delete/reset of earlier audit events.

## Execution ledger

- Replay unit tests initially failed on missing module; API tests failed on missing adapter argument, then passed after implementation.
- Independent review identified noncanonical restored events, a concurrent identical-step conflict, wrong-shape JSON escaping error handling, and blank script text allowing unreconstructable progress. Four repros failed before fixes. Strict stored-event models, audit-ID/key validation, identical pre-insert event recovery and upfront nonblank script validation address them.
- Final relevant tests: 15 passed, one existing Starlette/httpx deprecation warning. No full suite, AWS calls, live database writes or DDL run. Compile/whitespace checks passed.
- Preserved other-agent ownership and shared-checkout changes; no git add, commits or protected data/schema edits.
- Actual Exasol commit/concurrency behavior and canonical seed remain integration gates. Only replay progress is durable; analysis is recomputed and clinical APIs remain explicit.
