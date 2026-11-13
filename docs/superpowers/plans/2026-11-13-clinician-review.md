# Clinician Review Implementation Plan

> Use Superpowers test-driven-development and executing-plans. Continue the agreed FastAPI service.

**Goal:** Save explicit accepted/overridden/deferred clinician decisions and audit records atomically, with repeat-safe request keys.

**Architecture:** New review models and Exasol repository plus injected API routes. Use only existing canonical FINDING, CONSULTATION, PATIENT, CLINICIAN_REVIEW and AUDIT_LOG columns. No DDL or seed changes. Synthetic loopback development only; reviewer identity is supplied explicitly, not authenticated.

**Spec:** PROJECT.md human-oversight requirement and agreed schema contract.

## Tasks

1. Fix long/oblong detection and resolution with targeted regression tests against synthetic appearance records; preserve original text spans.
2. Define review commands: idempotency key, reviewer, decision and note; require a nonblank override reason. Define POST `/api/v1/consultations/{consultation_id}/findings/{finding_id}/reviews`.
3. Implement atomic review and audit insert in a non-autocommit connection; verify finding-to-consultation and synthetic-patient binding. Derive bounded deterministic IDs from consultation/key; store the full command fingerprint in the audit detail and reject key reuse or hash collision with different content. Explicitly reject conflicting already-completed decisions; do not silently supersede them.
4. Test successful transaction, repeated identical requests, conflicting keys, wrong consultation, rollback and API 404/409/503 states using fake storage at the connection boundary. Do not write to live MEDGUARD before canonical setup.
5. Independent code review and relevant tests only. Document endpoint and deferred authenticated sessions/clinical ordering integration. No staging or commits without coordination with the other agent.

## Review focus

Atomicity, replay/collision handling, concurrency conflicts, cross-consultation writes, false saved acknowledgements and override notes. Existing schema provides no revision column: request-key replay is supported, not general session revision concurrency.

## Execution ledger

- Ownership: never edit 01_schema.sql, seed.py, data/demo except listener-segment.json, data/reference, or fetch_labels.py. No DDL against MEDGUARD. No AWS default sessions, git add or commits.
- Long/oblong regression tests were observed failing, then passed after detector/resolver updates. Existing original-span behavior remains intact.
- Review model/repository tests failed before implementation; new API tests then failed on the missing adapter before it was added. Targeted listener/resolution/review run: 55 passed, one existing Starlette/httpx warning. No full suite or live database writes run.
- Compile and whitespace checks passed. Independent review is in progress at this checkpoint.
- Independent review completed with no significant findings. Reviewer also exercised collision, uncertain-commit replay and lost-connection recovery against in-memory storage. Actual Exasol transaction/concurrency verification remains pending canonical setup tonight.
