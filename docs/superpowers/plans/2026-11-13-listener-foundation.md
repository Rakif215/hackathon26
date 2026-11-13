# Listener Foundation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task with test-first verification.

**Goal:** Deliver a runnable, stateless transcript-analysis core shared by FastAPI and a direct-invocation Lambda adapter.

**Architecture:** Strict Pydantic contracts wrap a pure, conservative English demo-vocabulary detector. Both adapters call the same function; neither writes clinical state, confirms medicine identity, invokes Bedrock, or claims deployment.

**Tech stack:** Existing Python, FastAPI, Pydantic, pytest and HTTPX. No additional dependencies.

**Spec:** PROJECT.md and 2026-11-13-listener-serverless-design.md.

## Global constraints

- Synthetic scripted text only. No audio, clinical advice, medication confirmation or source-backed interaction claims in this extraction stage.
- Text offsets use half-open Python Unicode character indices into the unmodified input.
- Results always expose limitations, matched transcript evidence and a clinician clarification path.
- Stateless analysis is deliberately separate from future persisted processing/idempotency. Do not label results saved or integrated.

## Review focus

Negation, another person's medication, historical statements, partial segments and non-ASCII spans must not silently establish current patient exposure. Unknown knee painkillers must not become ibuprofen/NSAIDs.

## Task 1: Contracts and detector

Files: `src/hackathon26/listener/{__init__,models,detect}.py`, `tests/unit/test_listener.py`.

Interface: `detect_mentions(segment: TranscriptSegment) -> ListenerResult`.

- [x] Write tests covering literal named medicines, vague pill appearance, knee painkillers, negation/subject/temporal uncertainty, Unicode offsets, partial segments, strict validation and no-match limitations.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_listener.py -q`; verify missing implementation failure.
- [x] Implement bounded strict input models and conservative clause-local rules; unsupported contexts retain uncertainty.
- [x] Re-run focused tests; confirm extraction never produces confirmed drug IDs or risk findings.

## Task 2: Transport adapters

Files: `src/hackathon26/api.py`, `src/hackathon26/listener/lambda_handler.py`, `tests/api/test_listener_api.py`.

Interfaces: `create_app() -> FastAPI`; `handler(event, context) -> dict`. HTTP `POST /api/v1/listener/analyze` and `GET /health/live`. Lambda accepts the same segment JSON directly; it is not an SQS consumer yet.

- [x] Write tests for transport parity, 422 malformed input, partial-input status, process health and absence of persistence/Bedrock integration claims.
- [x] Run focused tests and observe missing-adapter failure.
- [x] Implement thin adapters and document Lambda input validation behavior (raises validation errors for failed direct invocations).
- [x] Run the full suite and compare HTTP/Lambda outputs.

## Task 3: Runnable example and handoff

Files: `data/demo/listener-segment.json`, `docs/listener.md`.

- [x] Document local startup, curl example, direct Lambda invocation, limitations and next integration gates.
- [x] Exercise the fixture against the real app using TestClient; verify no inferred medicine identity.
- [x] Run full pytest suite, compile checks and `git diff --check`.
- [x] Obtain a fresh review, address significant findings with regression tests, and report exact coverage limits.

## Execution ledger

- Ruling: Work in the existing feature checkout without changing branches or creating a worktree, preserving ongoing uncommitted setup edits. New listener files have disjoint scope; no unrelated changes will be staged or committed.
- Ruling: The first Lambda adapter is direct-invocation only; queue consumption and durable processing require the later stateful service and are not simulated by an in-memory cache.
- Tasks 1–2 implemented: focused detector tests and adapter tests were written before their modules, observed missing-module failures, then passed. Full suite: 32 passed; one dependency deprecation warning (Starlette recommends httpx2).
- Task 3 verification: real loopback Uvicorn GET/POST both returned 200; the synthetic fixture yielded APPEARANCE and INDICATION mentions with persisted=false. Server stopped after the smoke test. Compile and whitespace checks passed.
- Ruling: Renamed API test to test_listener_api.py to avoid pytest's duplicate-basename import collision without modifying existing pytest settings.

- Final review: independent reviewer found negation scope, mixed-subject attribution and temporal-context errors. Five regression inputs were observed failing, then fixed; full suite 37 passed, with the same Starlette/httpx deprecation warning.
- Ruling: Past-time cues conservatively qualify the whole sentence, even across clauses, to avoid claiming current exposure; this may understate current use in complex mixed-time statements and requires clinician clarification.
- No commits, AWS mutations or database changes performed. Existing setup edits remain untouched.
