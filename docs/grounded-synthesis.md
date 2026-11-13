# Grounded synthesis worker

POST `/api/v1/patients/{patient_id}/evidence/summarize` with the same body as an evidence check:

```json
{"as_of":"2026-11-13","candidate_drug_id":4}
```

The API fetches patient-specific evidence from Exasol and verifies it server-side. It does not accept a client-provided “verified” evidence packet. Unknown patients/candidates and unavailable storage retain the evidence endpoint's 404/422/503 behavior. The old six-table database will still return 503 until canonical setup.

When verified findings exist, Claude selects exact quotes and complete lab references in structured JSON. The application requires every rule exactly once, matching section IDs, unchanged quotations and the exact set of lab IDs. Unknown fields and unsupported prose are rejected. The displayed heading is fixed: “Potential interaction for clinician review.” This is deliberately extractive synthesis, not free-form clinical interpretation. Full source evidence, dated labs, uncertainty and limitations remain attached.

| Synthesis status | Meaning |
|---|---|
| GENERATED | Complete exact selections validated and an output Guardrail assessment trace was present. |
| NOT_REQUESTED | No verified findings; model was not called. |
| BLOCKED | Guardrail intervened; no model text published. |
| UNAVAILABLE | Configuration, transport or bounded-input problem; verified evidence retained. |
| INVALID_OUTPUT | Output/reference/coverage/stop-reason or assessment confirmation failed; no summary published. |

Guardrail status distinguishes ASSESSED, INTERVENED, UNCONFIRMED, NOT_CONFIGURED and NOT_REQUESTED. Guardrail assessment is not a guarantee of clinical correctness. A masked or blocked response is conservatively withheld. Raw model reasoning and guardrail traces are never returned or logged by this service.

An input assessment alone cannot establish guarded output. An explicit intervention stop reason is retained even if the service omits its output message. Lab references must be integer JSON values; booleans, strings and floats are rejected rather than coerced.

`BEDROCK_GUARDRAIL_ID` and a positive numbered `BEDROCK_GUARDRAIL_VERSION` are read from the existing environment configuration. Missing configuration or DRAFT never falls back to an unguarded call. The helper creates clients only through `hackathon26.bedrock.session()`, tags input as guardContent, sets token/time limits, disables automatic SDK retries and shares the existing process rate limiter. The older `ask()` helper remains separate and is not used by this worker.

Limits: 48,000 input characters, 64 selections, 64,000 output characters, 2,048 generation tokens, 5-second connection and 30-second socket read timeouts. Socket timeouts are not a strict end-to-end job deadline. Oversized/incomplete output is withheld rather than silently truncated into a partial result. There are no automatic application retries.

Direct Lambda entry point: `hackathon26.synthesis.lambda_handler.handler`:

```json
{"patient_id":1,"request":{"as_of":"2026-11-13","candidate_drug_id":4}}
```

This handler re-fetches and verifies evidence before model use. It is a direct-invocation adapter, not yet an SQS consumer. No Lambda is deployed by this change. The current sandbox-profile session helper is for local execution; agree on explicit cloud execution-role support before deploying. Account-wide queue pacing, durable job identity, Exasol network access and retry/DLQ policy are also deployment prerequisites. A process-local limiter alone does not satisfy the workshop cap across independent workers or other team callers.

No findings, reviews or audit events are persisted here; `persisted` remains false. Reviewer/session authentication and persisted finding creation remain separate integration work.

Focused tests:

```sh
uv run pytest tests/unit/test_synthesis.py tests/unit/test_guarded_bedrock.py tests/unit/test_synthesis_lambda.py tests/unit/test_bedrock_session.py tests/api/test_synthesis_api.py -q
```

AWS references: [Converse Guardrail integration](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html), [Converse input blocks](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html).
