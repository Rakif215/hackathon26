# Consultation Workbench Plan

> Use Superpowers TDD with focused tests only. No seed/schema edits, live writes, staging or commits.

**Goal:** Provide one frontend-oriented, consultation-bound operation combining existing replay, candidate resolution, evidence validation and optional guarded synthesis.

**Contract:** POST `/api/v1/consultations/{id}/replays/{replay_id}/workbench` takes expected_sequence, optional candidate_drug_id, and include_synthesis=false. Patient ID, transcript and date come from the replay, not caller input. Evidence is checked only for an explicitly supplied candidate; synthesis additionally requires explicit opt-in. No inferred clinical actions or persisted findings.

**Behavior:** READY when no utterance has been revealed. COMPLETE when requested stages complete, including verified no-hit results. PARTIAL when a dependency or synthesis fails, retaining usable stages and structured problems. Unknown candidate is 422, unknown replay 404, stale/changed state 409, unavailable replay 503. Recheck the replay cursor after processing to reject results if a user advanced concurrently.

## Tasks

1. Tests first: patient binding, no inferred candidate, explicit evidence/synthesis, missing dependencies, ready replay, stale cursor and concurrent advancement.
2. Implement strict request/result contracts and injected coordinator; expose thin API router.
3. Use the newly supplied shared MatchLevel enum in our resolution code; leave the other agent's module untouched.
4. Focused workbench/resolution/adapter tests, independent review, compile/whitespace checks and frontend handoff docs. No full test suite or paid/model/live DB calls needed.

## Execution ledger

- Workbench tests failed before implementation; API tests then returned 404 until the router was added. Resolution uses imports from the other agent's MatchLevel enum without modifying that module.
- Coordinator returns active medication rows, resolution and explicitly requested evidence/synthesis. No automatic drug selection, navigation or persistence occurs.
- Independent review identified future-dated labels passing source checks and malformed provider stop reasons discarding completed stages. Both regression cases failed before fixes; future labels are withheld and malformed provider replies yield partial/invalid synthesis outcomes.
- Final relevant run: 63 passed in 0.55 seconds, one existing Starlette/httpx warning. Included workbench, resolution and the changed evidence/gateway boundaries only; no full suite or live DB/AWS calls. Compile/whitespace checks passed.
- No protected schema/seed/data files changed and no staging or commits. Persisted finding creation and live canonical integration remain unfinished dependencies.
