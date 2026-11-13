# Patient Medication Resolution Implementation Plan

> Use superpowers:executing-plans and test-driven-development. Authorized continuation of the listener work.

**Goal:** Resolve extracted mentions against a synthetic patient's active recorded medication list, preserving alternatives and uncertainty.

**Architecture:** Pure resolver plus injected read-only Exasol repository. POST `/api/v1/patients/{patient_id}/listener/resolve` accepts a TranscriptSegment and an explicit as_of date. The server extracts mentions itself, fetches only that patient's current medications, and returns candidates with named match levels and row-level provenance. No confirmation, persistence or interaction claim.

**Spec:** PROJECT.md, listener-serverless-design.md and the separately authored demo-data-foundation requirements (canonical numeric patient IDs; NAME_MATCH, COLOUR_SHAPE_MATCH, COLOUR_MATCH, UNRESOLVED vocabulary).

## Constraints and review focus

- Do not change seed/schema/data-foundation files. Database errors are 503, missing synthetic patient is 404, never a fabricated empty list.
- Date filtering respects start/stop dates; explicit as_of is required for deterministic replay.
- No global pill search, class inference from knee pain, invented probabilities or automatic confirmation.
- Exclude historical, negated and other-person mentions from current-patient candidate resolution. Unknown subject/context requires clarification.
- Match all extracted appearance constraints, not just color. Missing product metadata cannot establish a match. Preserve multiple appearance/manufacturer alternatives and current medication strength filtering.
- Each result identifies source medication rows and appearance provenance; label/lab checks remain explicitly unperformed.

## Tasks

1. Write failing pure tests for ambiguous white pills, narrowed shape, conflicting attributes, names, unidentified indication, excluded context, provenance and partial segments. Define models and implement conservative resolver.
2. Write repository tests with a small fake connection at the external I/O boundary; assert synthetic-patient restriction, bound query parameters, date filters, unknown patient and failure distinction. Implement read-only adapter using existing db.connect.
3. Write API tests for path/body validation, candidate result, missing patient, database outage and partial input. Implement injected repository and endpoint without touching existing listener contracts.
4. Run full suite, independent review, compile/whitespace checks; update listener docs and record verified limitations. No cloud mutations or DB writes.

## Execution ledger

- Work in current feature checkout; preserve unrelated uncommitted work. Test fixtures exist only in tests; default API uses Exasol.
- Tasks 1–3 implemented test-first: detector/resolver and repository tests initially failed on missing modules; API tests failed on missing injection argument, then passed after implementation. Full suite: 53 passed, one existing Starlette/httpx deprecation warning.
- Read-only live catalog check: PATIENT exists; DRUG, DRUG_APPEARANCE and PATIENT_MEDICATION are absent. End-to-end live resolution is blocked on the separate data-foundation work; no schema changes were attempted.
- Compile and whitespace checks passed. Independent review pending at this checkpoint.
- Independent review completed: linked name/appearance conflicts, missing referenced drug rows and lost imprint alternatives were identified. Three regression tests failed before fixes; the resolver now flags unsupported appositive descriptions, retrieval uses a left join so invalid drug references fail validation, and candidates retain imprint provenance.
- Final suite: 56 passed, one existing dependency warning; compile and whitespace checks passed. Actual default API against the current legacy database returned 503 with the sanitized unavailable/incompatible message, as intended. No successful live resolution is claimed.
- Remaining integration: canonical data foundation and patient-bound persisted consultations. Linked-description reconciliation currently handles adjacent comma appositives; broader coreference remains limited by the documented demo-language scope.
