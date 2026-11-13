# Grounded Synthesis Worker Plan

> Execute with Superpowers test-driven-development. Run only synthesis/Bedrock/API tests relevant to this change.

**Goal:** Add Guardrails-enabled, bounded extractive synthesis of server-verified evidence, with honest blocked/unavailable/invalid statuses.

**Architecture:** A guarded Bedrock helper uses hackathon26.bedrock.session() and the existing process limiter, explicit timeouts and no automatic SDK retries. Claude returns JSON selecting exact quotes and lab IDs from the supplied findings. The service requires full finding coverage and exact source/lab references, then renders fixed clinician-review phrasing alongside the original evidence. No free-form clinical narrative is published.

**Scope:** New synthesis module, HTTP endpoint and direct Lambda handler; no deployment, DDL, seed files, staging or commits. Lambda transport uses the same evidence retrieval/verification path, not client-asserted verified evidence. Cloud execution-role support and account-wide queue pacing remain deployment prerequisites.

## Tasks

1. Write tests for valid exact selections, unknown/omitted/duplicate rules, altered quotes, invented labs, missing labs, no-hit/unverified bypass, and blocked/unavailable/malformed responses. Implement strict output validation and evidence-preserving fallback.
2. Test and implement guarded Converse with configured Guardrail, guardContent blocks, shared pacing, bounded tokens/timeouts, stop-reason handling and trace assessment status. No unguarded fallback.
3. Test HTTP adapter and direct Lambda adapter; HTTP re-fetches and validates evidence from the repository. Invalid/missing Guardrail configuration does not call the model. Run focused tests and independent review.

## Review focus

Unverified input, model-invented sources, incomplete output, trace/log privacy, injected prompt-like source content, failure masquerading as successful synthesis, and profile isolation. Source selection is not clinical interpretation or proof of actual exposure.

## Execution ledger

- New synthesis tests failed on missing implementation before modules/adapters were added. Focused synthesis/Bedrock/API tests passed; no full suite was run.
- A bounded synthetic Bedrock smoke call completed with exact selection and assessment trace. No database or resource mutations were performed.
- Independent review found input-only assessment acceptance, coercible lab IDs and loss of intervention status when output was absent. Five regression cases were observed failing, then fixed: output assessment required, strict integer references, independent stop-reason parsing.
- Final focused run: 32 passed with one existing Starlette/httpx deprecation warning. Compile and whitespace checks passed. No staging/commits and no protected data/schema files edited.
- Deployment limitations: local sandbox profile helper only, process-local pacing, no queue/idempotent job ledger, and canonical Exasol foundation still pending. Lambda adapter exists but is not deployed.
