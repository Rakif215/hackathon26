# Read-only evidence checks

Start the FastAPI app as described in [listener.md](listener.md), then use Swagger at `/docs` or POST to `/api/v1/patients/{patient_id}/evidence/check`:

```json
{"as_of": "2026-11-13", "candidate_drug_id": 4}
```

Alternatively supply `candidate_class_name`, for example `NSAID`, instead of a drug ID. Exactly one is required. Class names are exact stored codes; this is a hypothetical candidate check, not proof that the patient takes a medicine in that class. Use actual canonical database IDs rather than assuming the example ID.

The repository checks the synthetic patient and candidate mapping, then joins the candidate classes, active patient medications, curated rules, label sections and the patient's dated labs. The candidate must supply a required class, and the full required class combination must be present. A matching rule without recent labs remains a match with an explicit missing-lab limitation.

Each source quotation must be nonblank and an exact, case-sensitive contiguous substring of its stored section. The SHA-256 of the original UTF-8 section must match the stored hash. Missing source identity, inconsistent rule evidence or invalid lab rows block publication of every finding in the response. Quotes and source text are never normalized. Hash verification establishes consistency with the stored section, not independent authenticity or completeness of the reference database.

Response states:

| State | Meaning |
|---|---|
| `EVIDENCE_FOUND` | Stored source text verifies; dated labs and limitations accompany the candidate-based match. |
| `EVIDENCE_UNVERIFIED` | One or more quote, hash, metadata or row checks failed; no findings published. |
| `NO_DOCUMENTED_INTERACTION_FOUND` | Known candidate and patient, but no stored curated rule matched. Coverage remains limited. |
| HTTP 404 | Synthetic patient not found. |
| HTTP 422 | Invalid request or unknown candidate class mapping. |
| HTTP 503 | Evidence storage unavailable or incompatible. |

Labs are selected within the inclusive 365-day window ending at `as_of`. Reference flags compare values against their stored bounds, not diagnostic or treatment thresholds. Units and measurement dates remain visible; no conversion or numerical trend is calculated. An over-90-days-old note is a demo display rule requiring clinician freshness review. It is not a clinical cutoff. Mixed or absent units are flagged.

No Bedrock synthesis, clinical severity assignment, medication change, clinician acceptance or audit write occurs here. `persisted` is false. The consultation/patient session binding and authentication remain later work; use loopback for synthetic development.

Canonical data-foundation requirements are prerequisites: `DRUG_CLASS`, `PATIENT_MEDICATION`, `RISK_RULE_CLASS`, evidence-linked `RISK_LAB_RULE`, hashed `DRUG_LABEL_SECTION` and `LAB_RESULT`, plus the synthetic patient record. The legacy six-table database does not satisfy these requirements. This change does not replace it or import labels.

Tests: `uv run pytest -q`. The optional `MEDGUARD_INTEGRATION=1 uv run pytest tests/integration/test_evidence_sql.py -q` runs read-only SQL with inline synthetic CTE records, without creating tables; it does not verify the actual canonical seed or public-source ingestion.

SQL references: [Exasol LISTAGG](https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/listagg.htm), [ADD_DAYS](https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/add_days.htm).
