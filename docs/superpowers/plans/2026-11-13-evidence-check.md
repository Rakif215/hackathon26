# Evidence Check Implementation Plan

> Use Superpowers test-driven-development and executing-plans. Continue the approved MedGuard architecture.

**Goal:** Add read-only evidence verification and a patient-specific evidence/lab endpoint without fabricating warnings or replacing legacy data.

**Spec:** PROJECT.md and demo-data-foundation requirements 10–13. Canonical schema application and reference ingestion remain separate work.

**Architecture:** One exact quote verifier; strict candidate request; constant parameterized Exasol join; pure hash/quote validator; API adapter. No model calls, prescribing, diagnosis, severity invention, persisted review or database mutations.

## Tasks and verification

1. Write failing tests for exact quotes (null/blank/case/Unicode/whitespace), content hashes, missing sources, invalid rows and missing labs. Implement pure evidence contracts and verification.
2. Write failing tests for synthetic patient and candidate lookup, unavailable storage and canonical Exasol parameters. Implement repository with one evidence join returning all required classes, supporting drugs, evidence and recent labs.
3. Add API tests and endpoint `POST /api/v1/patients/{patient_id}/evidence/check`, requiring as_of and exactly one candidate drug ID/class. Return explicit statuses; sanitize database errors at the HTTP boundary.
4. Run the full suite, independent review, compile and whitespace checks. Document local examples and canonical-schema dependency. Do not claim live evidence retrieval until the data foundation exists and actual SQL has been verified.

## Review focus

No-hit versus failure, fabricated/modified quotes, source metadata, absent/mixed-unit labs, candidate relevance, future/stale labs, missing rule evidence and wrong-patient joins. Class candidates are hypothetical checks, never inferred exposures.

## Execution ledger

- Baseline 56 tests pass. Canonical data foundation is not yet implemented. No destructive schema or seed changes authorized by this implementation slice.
- Tasks 1–3 implemented test-first; initial tests failed on absent modules before implementation. Exact quote/hash verification, missing-lab handling, candidate/patient lookup and API failure states are covered.
- Independent reviewer identified malformed URL parsing and blank source metadata. Regression inputs added; invalid URL reproduced a failure before correction; all now return unverified evidence.
- Opt-in real Exasol check initially failed on reserved alias NAMES; renamed to SUPPLYING_DRUG_NAMES. Read-only inline-fixture integration then passed (1 test, 6.82 seconds): six renal rows, class/drug parity, candidate relevance, patient isolation, potassium rule and missing labs.
- Final local suite: 90 passed, 1 opt-in test skipped, one existing Starlette/httpx deprecation warning. Compile/whitespace checks passed. No database mutations or AWS resource changes.
- Canonical stored seed, actual label authenticity/provenance ingestion and persisted consultation binding are not validated by inline-fixture tests. These remain explicit next dependencies.
