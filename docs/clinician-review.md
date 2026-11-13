# Clinician review API

POST `/api/v1/consultations/{consultation_id}/findings/{finding_id}/reviews`:

```json
{
  "idempotency_key": "review-001-accept",
  "reviewer": "Dr. Demo",
  "decision": "ACCEPTED",
  "note": "Evidence and limitations reviewed."
}
```

Use the existing canonical consultation/finding IDs. This endpoint does not create findings from read-only evidence checks. Decisions are ACCEPTED, OVERRIDDEN or DEFERRED. An override needs a nonblank note. Accepting a finding acknowledges its review; it does not authorize medication changes or clinical orders.

The store checks that the finding belongs to the named consultation and a synthetic patient, then saves CLINICIAN_REVIEW and AUDIT_LOG in one non-autocommit transaction. It returns `persisted: true` only after commit succeeds or an identical committed command is recovered from its audit receipt. Database errors are sanitized; a failed audit insert rolls back the review.

Retry a failed request using exactly the same idempotency key and body. Identical retries return the original receipt, including its original decision time. Reusing a key with different content returns 409. This first version allows only one review per finding: new keys do not overwrite or silently amend earlier decisions, including DEFERRED decisions. An amendment workflow is future work.

Review IDs equal finding IDs to enforce that one-review rule using the existing primary key. Audit IDs are deterministic bounded hashes of consultation plus request key to fit DECIMAL(10,0); a full command fingerprint detects hash collisions and fails closed. A collision or pre-existing conflicting ID may require a new key/operator investigation; nothing is overwritten.

The endpoint returns 404 for an absent/wrong-consultation/non-synthetic finding, 409 for conflicts, 422 for invalid commands and 503 when persistence cannot be confirmed. No successful saved receipt is returned on a 503. Keep the key for retries when commit outcome is uncertain.

Reviewer identity is supplied by the caller and is not authenticated. This is a loopback synthetic-development API, not a production clinical authorization system. UTC decision timestamps are stored in the canonical TIMESTAMP column; the JSON response carries UTC timezone information. Persistent session revisions and multi-review amendment policy are not implemented.

The live database is still the legacy six-table schema. Expect 503 until the other agent applies the canonical schema and creates findings. No live review writes or DDL were run during development.

Relevant tests: `uv run pytest tests/unit/test_reviews.py tests/api/test_review_api.py -q`.

Listener compatibility: both “the long white one” and “the white oblong one” now preserve their source spans and match the canonical oblong appearance. This change does not infer a product from size alone.
