# Implementation Plan: demo-data-foundation

## Overview

The implementation language is Python 3.11 (pyexasol, pydantic, pytest, hypothesis), as in the design.
Tasks follow the order of the visible demo path. Schema deltas and Match_Level come first, then the label
manifest, fetcher and snapshots, the Label_Importer, the Demo_Fixture with its validator and `build_rows`,
the Join_Status adapter, and the seed CLI. After that come one guarded live run against the AWS-hosted
Exasol, the PROJECT.md status update and the docstring.

Every implementation sub-task is test-first. Write the failing unit test, run it and see it fail, then
write the code until it passes. Unit tests stay offline. They never call `db.settings()` or `db.connect()`.
Seed tests use a fake `connect_factory`, and fetcher tests use a fake transport, clock and sleep.

Ownership boundary: a parallel agent owns `src/hackathon26/evidence.py`, `src/hackathon26/evidence_check/`,
`src/hackathon26/reviews/`, `src/hackathon26/resolution/`, `src/hackathon26/listener/`,
`src/hackathon26/synthesis/` and `src/hackathon26/api.py`. No task edits those modules. Tasks may import
and call them: `verify_quote`, `EvidenceRepository`, `EvidenceRequest`, `verify_rows`, `UnknownPatient`,
`UnknownCandidate` and `EvidenceStoreUnavailable`.

## Tasks

- [x] 1. Schema DDL deltas, Match_Level vocabulary and test tooling
  - [x] 1.1 Implement `src/hackathon26/schema_file.py` test-first
    - Write `tests/unit/test_schema_file.py` first, covering the following:
      - `split_statements` removes `--` comments, including the semicolon in the FINDING comment, splits on `;` and drops empty pieces.
      - `parse_tables` returns `ColumnDef` values (name, type text, base type, NOT NULL, DEFAULT, PK membership) in file order.
      - Live base-type parsing turns `VARCHAR(100) UTF8`, `TIMESTAMP(3)` and `CHAR(64) UTF8` into `VARCHAR`, `TIMESTAMP` and `CHAR`.
      - `classify_live_tables` marks tables `LEGACY_DROP` (the four legacy names, PATIENT with `LANGUAGE`, AUDIT_LOG with `EVENT_ID`/`ACTOR`/`EVENT_ACTION`), `CANONICAL_REPLACE` or `UNMANAGED`.
      - `compare_columns` reports missing and unexpected column names per table and ignores column order.
    - Then implement the module as specified in the design. It is pure: no I/O apart from the caller passing SQL text.
    - _Requirements: 2.4, 2.5, 2.6, 3.1, 3.2_

  - [x] 1.2 Apply the five adjustments to `sql/01_schema.sql` test-first
    - First copy the current 16-table file to `tests/fixtures/schema_before_feature.sql`. Before copying, confirm that `git diff main -- sql/01_schema.sql` is empty.
    - Add tests to `tests/unit/test_schema_file.py` that run against the real Schema_File and check the following:
      - DRUG_LABEL_SECTION has `CONTENT_SHA256 CHAR(64) NOT NULL`.
      - The RISK_RULE_CLASS table has the PK (RULE_ID, CLASS_NAME).
      - RISK_LAB_RULE has `EVIDENCE_SECTION_ID` and `EVIDENCE_QUOTE`, both NOT NULL, and the file has no FOREIGN KEY anywhere.
      - `MATCH_LEVEL VARCHAR(30) NOT NULL` is on DRUG_MENTION, MENTION_CANDIDATE and FINDING. DRUG_MENTION.CONFIDENCE, MENTION_CANDIDATE.SCORE and FINDING.CONFIDENCE are gone.
      - DRUG_MENTION has a nullable `RESOLVED_CLASS_NAME VARCHAR(200)`.
      - A `--` comment beside each added table and column states the reason. Each MATCH_LEVEL comment names the replaced column and lists all five codes in rank order. The FINDING comment also states the TRIGGER_DRUG_ID and MATCH_BASIS distinction.
      - Every other column is unchanged compared with `tests/fixtures/schema_before_feature.sql`.
      - The file defines exactly 17 tables.
      - The first two statements are `CREATE SCHEMA IF NOT EXISTS MEDGUARD` and `OPEN SCHEMA MEDGUARD`.
      - There is no `'` outside comments, and every statement has an idempotent form.
    - Then edit the DDL: update the header comment from 16 to 17 tables and the SECTION_TYPE comment so it includes `warnings_and_cautions`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.11, 2.9_

  - [x] 1.3 Implement `src/hackathon26/match_level.py` test-first
    - Write `tests/unit/test_match_level.py` first, covering the following:
      - Each of the five codes maps to its rank (1–5) and to its Glossary label.
      - `" NAME_MATCH"`, `"name_match"` and other non-members raise `UnknownMatchLevel`, with `repr(value)` in the message.
      - A source scan lists Match_Level literals outside `match_level.py`. Mark it `xfail(strict=True)` with the reason that `resolution/` is owned by the parallel agent (design gap 6).
    - Then implement `MatchLevel` (StrEnum), `UnknownMatchLevel`, `rank` and `label` with exact dict lookup and no stripping or case folding.
    - _Requirements: 1.9, 1.10_

  - [x] 1.4 Add `hypothesis` and write the Quote_Verifier property tests
    - Add `hypothesis` to the `dev` group of `pyproject.toml` only, run `uv sync`, and leave the other uncommitted edits in that file untouched.
    - Write `tests/unit/test_quote_properties.py` against the existing `hackathon26.evidence.verify_quote` (do not edit `evidence.py`).
      - **Property 1: Every non-blank substring verifies**
      - **Property 2: Anything that is not an exact substring is rejected.** Include whitespace, case and straight/typographic quote perturbations, empty and whitespace-only quotes, and a null text.
    - Use at least 100 examples each, over non-ASCII text. Add the `# Feature: demo-data-foundation, Property N: ...` comment.
    - The example cases for 11.4 and 11.5 already exist in `tests/unit/test_evidence.py`. Do not duplicate them.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 17.2_

  - [ ]\* 1.5 Write property test for the Schema_File splitter
    - **Property 6: The Schema_File splitter returns the statements in order**
    - **Validates: Requirements 2.4**

  - [ ]\* 1.6 Write property test for Match_Level lookup
    - **Property 7: Match_Level lookup is exact**
    - **Validates: Requirements 1.9, 1.10**

- [x] 2. Label manifest, Label_Fetcher and committed snapshots
  - [x] 2.1 Implement the manifest and metadata part of `src/hackathon26/labels.py` test-first
    - Write `tests/unit/test_labels.py` first, covering the following:
      - `load_manifest` rejects a missing Demo_Drug, a duplicate, an unknown drug and a malformed or uppercase set id, naming the entry.
      - `slug` turns "metoprolol succinate" into "metoprolol-succinate".
      - `request_url` returns `https://api.fda.gov/drug/label.json?search=set_id%3A%22<id>%22` built with `urllib.parse`.
      - `write_metadata` and `read_metadata` use the exact JSON form (sorted keys, `indent=2`, `YYYY-MM-DDTHH:MM:SSZ`, trailing newline). `read_metadata` rejects an empty URL, a bad timestamp and a bad SHA-256.
      - `check_response` enforces HTTP-200 body checks: `meta.results.total == 1`, one result, `set_id` equals the pin, and `generic_name` contains the entry name case-insensitively.
      - `content_hash` equals `hashlib.sha256(text.encode("utf-8")).hexdigest()`.
    - Then implement these functions plus the `IMPORTED_FIELDS`, `DEMO_DRUGS`, `OPTIONAL_DRUGS` and `SET_ID_RE` constants, and the `ManifestEntry`, `SnapshotMetadata` and `LabelError` types. Import only `urllib.parse` from `urllib`.
    - _Requirements: 7.1, 7.4, 7.5, 7.6, 7.10, 7.13, 9.11_

  - [ ]\* 2.2 Write property test for the Snapshot_Metadata round trip
    - **Property 4: Snapshot_Metadata survives a write and read**
    - **Validates: Requirements 7.10, 17.6**

  - [x] 2.3 Implement `scripts/fetch_labels.py` (Label_Fetcher) test-first
    - Write `tests/unit/test_fetch_labels.py` first, with a fake transport, clock, sleep and `now`, covering the following:
      - One GET per entry in manifest order to `request_url(set_id)`, with no API key and with the User-Agent header.
      - The response body is saved byte-for-byte to `<slug>.json`, and `<slug>.meta.json` is written. The generic name and SHA-256 are printed.
      - At least 1 s between attempt starts, retries included.
      - HTTP 429 waits at least 5 s, with at most 4 attempts.
      - Each failure keeps the old files (or creates none) and the run continues: 429 exhausted, other status, 404 or zero results, timeout or connection error, invalid JSON, failed `check_response`.
      - Exit codes are 0 when all entries are saved, 1 when any failed (every failure printed with its reason) and 2 for a manifest fault, with no request sent.
      - Writes go only under `data/reference/labels/`, through `.tmp` files and `os.replace`.
      - The script never imports `hackathon26.db`.
    - Then implement `fetch_all` and `main` with stdlib `urllib.request`, a 30 s socket timeout and a 30 s read-loop limit. It inserts `<repo>/src` on `sys.path` as `scripts/preflight.py` does.
    - _Requirements: 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.11, 7.12, 7.13, 7.14, 16.2_

  - [x] 2.4 Pin the remaining set ids and commit the Label_Snapshots
    - Create `data/reference/label_manifest.json` with ramipril pinned to `01da05d8-e72e-4208-bf92-a5cd929f15ab`.
    - Pin metoprolol succinate, furosemide and ibuprofen with a manual, read-only openFDA search, for example `search=openfda.generic_name:"furosemide"&limit=5`.
      - Choose a single-ingredient label, and an extended-release one for metoprolol succinate.
      - Leave out the Optional_Drugs (design decision 7).
    - Run `uv run python scripts/fetch_labels.py`, expect exit 0 and review `git diff data/reference`.
    - Confirm `.gitignore` excludes none of the new paths.
    - Add a test to `tests/unit/test_labels.py` that round-trips every committed `*.meta.json`, and that fails (not skips), naming the drug, if any manifest snapshot or metadata file is missing.
    - _Requirements: 7.1, 7.2, 7.5, 7.6, 7.10, 7.14, 16.4, 17.6, 17.7_

- [x] 3. Label_Importer with provenance
  - [x] 3.1 Implement `load_label` and `import_sections` in `src/hackathon26/labels.py` test-first
    - Commit the synthetic fixture `tests/fixtures/labels/examplamide.json` (≤ 20 KB) with a matching `examplamide.meta.json`. It contains the following:
      - at least two Imported_Section_Fields, one of them with two or more elements;
      - one empty-string element;
      - one non-imported field;
      - text with leading and trailing whitespace, line breaks and non-ASCII characters.
    - Write the tests first, covering the following:
      - One row per non-empty element and none for the empty element or the non-imported field.
      - SECTION_TEXT is exact and SECTION_TYPE is the field name.
      - `SECTION_ID = 1000·m + 100·f + e`, increasing in manifest, field and element order.
      - CONTENT_SHA256 equals a SHA-256 computed independently in the test.
      - Notices for the skipped empty element and for zero imported sections.
      - An element index ≥ 100 and a lone-surrogate text raise `LabelError`.
    - Write the `load_label` check tests first as well. Each one raises `LabelError` naming the drug and the check, before any database access:
      - snapshot missing;
      - metadata missing;
      - SHA-256 mismatch (the message includes `uv run python scripts/fetch_labels.py`);
      - invalid JSON;
      - `results` length ≠ 1;
      - no `set_id`;
      - `set_id` differs from the pin;
      - `effective_time` that is not 8 digits or not a calendar date.
    - Then implement both functions and `LoadedLabel`/`SectionRow`.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7, 8.8, 8.9, 8.13, 17.3, 17.14_

  - [x] 3.2 Test the committed snapshots end to end
    - In `tests/unit/test_labels.py`, import every committed Label_Snapshot and assert the invariant from Requirement 8.9 for every row.
    - Assert ramipril provenance: LABEL_SET_ID `01da05d8-e72e-4208-bf92-a5cd929f15ab`, LABEL_EFFECTIVE_AT 2022-07-01, SECTION_IDs 1500 (`drug_interactions[0]`) and 1400 (`warnings_and_cautions[0]`).
    - Assert that `verify_quote` accepts the two quotes from Requirements 10.4 and 10.5 against those sections.
    - _Requirements: 8.6, 8.9, 10.4, 10.5, 11.7, 17.7_

  - [ ]\* 3.3 Write property test for the Label_Importer
    - **Property 3: Imported sections are exact, complete and hashed**
    - **Validates: Requirements 8.3, 8.4, 8.5, 8.6, 8.8, 8.9**

- [x] 4. Checkpoint: ensure the whole suite passes
  - Run `uv run pytest -q`, which includes the parallel agent's tests under `tests/unit`, `tests/api` and `tests/integration`, and `uv run pytest tests/unit -q`. The unit run must be offline, with nothing skipped and in under 60 s.
  - Ensure all tests pass, and ask the user if questions arise.
  - _Requirements: 17.1_

- [x] 5. Demo_Fixture, validator, trust-text checks and row building
  - [x] 5.1 Create `data/demo/demo_fixture.json` and the loader in `src/hackathon26/demo_fixture.py` test-first
    - Write `tests/unit/test_demo_fixture.py` first. It reads the committed file, not a copy, and asserts the design values for the following:
      - PATIENT, the 3 medications, the 3 appearances (SRC_NAME 'synthetic …', fictional manufacturers, IMPRINT null, STRENGTH copied) and the 9 labs;
      - CONSULTATION, the 10 utterances from the Demo_Script table, the 3 class synonyms with CURATED_BY;
      - the 6 drugs with RXCUI and IS_OTC, and the 4 Demo_Drug classes with CLASS_TYPE EPC (plus the optional 105/106 records);
      - the 3 risk rules with required classes, evidence (drug, field, element), the verbatim quotes, CONCERN_AT null and RATIONALE.
    - The loader tests also check that an unknown key, an empty string and a float decimal are rejected with the JSON path.
    - Then write the JSON and a strict, frozen pydantic `DemoFixture` with `extra="forbid"`, with dates as `YYYY-MM-DD`, the start time without a zone and decimals as strings, plus `load_fixture` and `FixtureError`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.8, 5.1, 5.2, 5.3, 5.7, 6.1, 6.4, 6.8, 6.9, 9.1, 9.2, 9.4, 9.7, 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.9, 16.4_

  - [x] 5.2 Implement `fixture_problems` test-first
    - Write the tests first. The committed fixture plus committed snapshots must give no problems. Hand-written mutations must each return a `Problem` with the mutated JSON path and the requirement number. The mutations are:
      - an unknown drug in a medication or appearance (4.10);
      - colour, schedule or shape breaks (4.6, 4.7);
      - a MANUFACTURER equal to a snapshot `manufacturer_name` in different case (4.9);
      - lab faults: a null value or unit, REF_LOW ≥ REF_HIGH, a date outside the window, a duplicate date, a broken trend, or the latest value moved inside its range (5.4–5.6, 5.8);
      - script faults: a speaker swap, a SEQ gap or duplicate, a required phrase in the wrong case, a drug name inserted, an offset step below 2000, a last offset above 90000, a digit, "mg" or "twice a day", whitespace-only or 4001-character text (6.2–6.11);
      - class faults: wrong-case or unknown required class (9.9), ungrounded class (9.8);
      - a quote with one character changed (10.6, via `verify_quote`);
      - a manifest/fixture drug mismatch (9.1, 9.11);
      - an over-length value (8.11).
    - Then implement `Problem` and `fixture_problems` and `evidence_sections`, calling `hackathon26.evidence.verify_quote` only.
    - _Requirements: 4.6, 4.7, 4.9, 4.10, 5.4, 5.5, 5.6, 5.8, 6.2, 6.3, 6.5, 6.6, 6.7, 6.10, 6.11, 8.11, 9.1, 9.8, 9.9, 9.11, 9.12, 10.6, 11.7, 17.4, 17.7_

  - [x] 5.3 Implement the trust-text checks test-first
    - Create `tests/unit/trust_rules.py` with the following:
      - the Banned_Phrase_List, with four categories (dose change, starting or stopping a medicine, diagnosis statement, prescribing recommendation) and at least two phrases each;
      - a whole-word matcher (case-insensitive, bounded by a string edge or a non-alphanumeric character).
    - Add `curated_text()` to `demo_fixture.py`. It yields `(json_path, value, is_utterance)` and excludes label text, quotes, PRIMARY_DX, STRENGTH and SCHEDULE_TEXT.
    - Write `tests/unit/test_trust_text.py`. It asserts the following:
      - No Curated_Text contains a trust word, and no non-utterance Curated_Text contains a banned phrase. Each failure reports the JSON path and the matched word.
      - No banned phrase matches "once a day", "twice a day", "three times a day", "in the morning" or "with breakfast".
      - The checks reject a sample for each trust word and each category, and accept "no documented interaction found".
      - "Safety" and "safe," match, and "unsafe" does not.
    - _Requirements: 14.1, 14.2, 14.4, 14.5, 14.6_

  - [x] 5.4 Implement `build_rows` and `to_wire` test-first
    - Write the tests first, covering the following:
      - Every Seed_Owned_Table is built, and each row has exactly the Schema_File columns parsed by `schema_file.parse_tables`.
      - The expected row counts match the design table.
      - DRUG.BRAND_NAMES is the joined `brand_name` list or null. DRUG.SOURCE_FETCHED_AT comes from the metadata. DRUG.SRC_NAME contains 'openFDA', the set id and 'RxNorm'.
      - DRUG_CLASS.SRC_NAME is 'curated; openFDA EPC: <first EPC>', or exactly 'curated' when the list is absent or empty.
      - RISK_LAB_RULE.EVIDENCE_SECTION_ID is 1500/1500/1400. SRC_NAME contains the set id and SECTION_TYPE.
      - RISK_RULE_CLASS has 7 rows.
      - Two builds are equal, with the same primary keys.
      - Every date and timestamp occurs in the fixture, the metadata `fetched_at` or the snapshot `effective_time`.
      - `to_wire` converts Decimal to `"0.97"`, date to `"YYYY-MM-DD"`, and naive or UTC-aware datetime to `"YYYY-MM-DD HH:MM:SS.000000"` with no zone conversion.
    - Then implement both functions as pure code that reads no clock, environment or random source.
    - _Requirements: 3.3, 3.4, 3.5, 3.9, 4.5, 8.6, 9.1, 9.3, 9.5, 9.6, 9.10, 10.4, 10.5, 10.8, 10.10, 17.5_

  - [ ]\* 5.5 Write property test for row building
    - **Property 5: Row building is deterministic and every date is traceable**
    - **Validates: Requirements 3.4, 3.5, 3.9, 17.5**

  - [ ]\* 5.6 Write property test for the fixture validator
    - **Property 8: The fixture validator catches every single fault**
    - **Validates: Requirements 4.6, 4.7, 4.9, 4.10, 5.4, 5.5, 5.6, 5.8, 6.2, 6.3, 6.5, 6.6, 6.7, 6.10, 6.11, 9.8, 9.9, 9.12, 10.6, 17.4**

  - [ ]\* 5.7 Write property test for the trust-word matcher
    - **Property 9: The trust-word matcher finds whole words only**
    - **Validates: Requirements 14.1, 14.6**

- [x] 6. Join_Status adapter
  - [x] 6.1 Implement `src/hackathon26/join_verification.py` test-first
    - Write `tests/unit/test_join_verification.py` first, with a fake `EvidenceSource`, covering the following:
      - Both or neither candidate gives UNKNOWN_CANDIDATE, naming both parameters, and `fetch` is never called.
      - `UnknownPatient` gives UNKNOWN_PATIENT. `UnknownCandidate` gives UNKNOWN_CANDIDATE naming the candidate.
      - `EvidenceStoreUnavailable` with a database `__cause__` gives QUERY_FAILED carrying the redacted cause message.
      - Rows passed to the real `verify_rows` give the following:
        - EVIDENCE_UNVERIFIED for a bad quote, naming RULE_NAME and SECTION_ID;
        - EVIDENCE_UNVERIFIED for a bad hash;
        - NO_DOCUMENTED_INTERACTION_FOUND with "no documented interaction found" for zero rows;
        - EVIDENCE_FOUND with an empty lab list and the "no <ANALYTE> result in the 365 days up to <As_Of_Date>" limitation for null lab columns.
      - `format_report` prints quote, source, suppliers, labs with "outside reference range: yes/no", and no trust word.
    - If the existing `verify_rows` output differs from a requirement (design gaps 1–5), record it in the test as an `xfail(strict=True)` with the reason. Do not edit `evidence_check/`.
    - Then implement `JoinVerification`, `verify_join` (returns, never exits) and `format_report`.
    - _Requirements: 12.13, 12.14, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.12, 13.13, 13.14, 14.3, 17.12_

- [x] 7. Checkpoint: ensure the whole suite passes
  - Run `uv run pytest -q` across the whole suite, including the parallel agent's tests.
  - Ensure all tests pass, and ask the user if questions arise.
  - _Requirements: 17.1_

- [x] 8. Seed_Command CLI (`src/hackathon26/seed.py` rewrite)
  - [x] 8.1 Rewrite argument handling and offline validation test-first
    - Write `tests/unit/test_seed_cli.py` first, using a fake `connect_factory` that records calls and SQL. It covers the following:
      - `--reset`, alone or with other options, prints the retirement message naming `--apply-schema` and exits 2 before `connect_factory` is called.
      - `--apply-schema --verify` prints "cannot be combined" and exits 2 without connecting.
      - A broken fixture, a missing snapshot, a SHA-256 mismatch or a failed rule quote exits 3 with no connection and prints the path, drug or check.
    - Source scans check the following:
      - `seed.py` has no `CREATE TABLE` or `ALTER TABLE` and no legacy row building, and names the four legacy tables only in Schema_Apply code.
      - `seed.py`, `labels.py`, `demo_fixture.py`, `schema_file.py` and `join_verification.py` import no `urllib.request`, `http.client`, `socket`, `boto3`, `requests` or `hackathon26.bedrock`.
    - Then replace the legacy seed. Put `<repo>/src` on `sys.path` when the file runs as a script. Add `main(argv, *, connect_factory, out, err)`, argparse with a hidden `--reset`, and offline validation that runs before any connection.
    - _Requirements: 2.10, 3.10, 4.10, 8.2, 8.7, 8.11, 9.11, 9.12, 10.6, 15.1, 15.4_

  - [x] 8.2 Implement the Default_Seed_Run test-first
    - Add tests first, covering the following:
      - The connection uses `schema=""`, `autocommit=False` and `connection_timeout=30`.
      - A `connect()` error exits 4 with host:port and a sentinel password redacted.
      - The column check against `SYS.EXA_SCHEMAS` and `SYS.EXA_ALL_COLUMNS`: a mismatch prints the table, missing and unexpected columns and `--apply-schema`, exits 5 and writes nothing.
      - An NLS format mismatch exits 7 and writes nothing, with no `ALTER SESSION`.
      - Each of the 12 Seed_Owned_Tables, in fixed order, gets `DELETE FROM MEDGUARD.<t>` and then `insert_multi(("MEDGUARD", t), wire_rows, columns=cols)`.
      - There are no writes to App_Written_Tables.
      - The storage round trip: a missing SECTION_ID, changed text or bad hash rolls back and exits 7, naming SECTION_ID, drug and SECTION_TYPE.
      - An insert error rolls back and exits 7, naming the table.
      - After COMMIT, all 17 table counts are printed.
      - `verify_join(1, 2026-11-13, candidate_drug_id=104)` runs, and the run exits 0 on EVIDENCE_FOUND or 8 with no rollback otherwise.
      - Every printed error goes through `redact()`.
    - Then implement the run. Build the post-seed `EvidenceSource` as `EvidenceRepository(lambda: connect(schema="", connection_timeout=30))`.
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.7, 3.8, 3.9, 3.11, 8.10, 8.12, 13.8, 13.9, 13.11, 15.3, 16.1, 16.2, 16.3, 16.5, 16.6_

  - [x] 8.3 Implement Schema_Apply (`--apply-schema`) test-first
    - Add tests first, covering the following:
      - The connection uses `autocommit=True`.
      - Before any DROP or CREATE, the run prints host, port, database version and MEDGUARD, then every live table with its row count and its mark ("to be dropped", "to be replaced empty", "unmanaged, left unchanged").
      - Legacy tables are dropped as `MEDGUARD.<t>`, and Schema_File statements then run in file order. CREATEs come only from the Schema_File, and unmanaged tables are untouched.
      - The first failing statement stops the run, prints the target table or statement text, the error and "Statements executed before this failure stay applied", skips the seed and exits 6.
      - A re-run after a failure completes.
      - The post-check covers columns with base types, no legacy-only names and zero App_Written rows.
      - The run then continues into the Default_Seed_Run in the same invocation.
      - No DDL is executed without the option.
    - Then implement it in `seed.py`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 15.2, 15.3, 16.3_

  - [x] 8.4 Implement Verify_Mode (`--verify`) test-first
    - Add tests first, covering the following:
      - Verify_Mode loads only the Demo_Fixture (a load error exits 3).
      - It runs `verify_join` for patient 1, 2026-11-13 and drug 104, and prints `format_report`.
      - The recorded SQL contains only `SELECT`s, with no DML or DDL.
      - It exits 0 on EVIDENCE_FOUND and 8 otherwise.
    - Then implement it in `seed.py`.
    - _Requirements: 13.10, 13.11, 15.3, 16.5_

  - [ ]\* 8.5 Write the opt-in Integration_Check `tests/integration/test_seed_integration.py`
    - Module-level `skipif(os.getenv("MEDGUARD_INTEGRATION") != "1")`. It opens no connection and resolves no credentials when skipped.
    - A session fixture calls `pytest.fail` (not skip) for "no Exasol credentials resolve", "Target_Database cannot be reached" or "Canonical_Table missing or mismatched", with the message redacted.
    - Run the Default_Seed_Run twice as subprocesses and assert the following:
      - both runs exit 0;
      - the 17 table counts are equal after both runs;
      - the Seed_Owned rows are equal, ignoring order;
      - the App_Written rows are unchanged from before the first run.
    - Call `verify_join` read-only for these cases:
      - ibuprofen 104 and class 'NSAID' each give the two triple-whammy rules, with ramipril and furosemide as suppliers and the EGFR and CREATININE values;
      - ramipril 101 gives the potassium rule;
      - the flags are TRUE exactly for EGFR 55 and 48, CREATININE 1.20 and POTASSIUM 5.1;
      - metoprolol succinate 102 gives NO_DOCUMENTED_INTERACTION_FOUND;
      - patient 999 gives UNKNOWN_PATIENT;
      - 'nsaid' gives UNKNOWN_CANDIDATE.
    - The test never runs `--apply-schema`.
    - _Requirements: 12.8, 12.9, 12.10, 12.11, 17.8, 17.9, 17.10, 17.11, 17.13_

- [x] 9. Checkpoint: ensure the whole suite passes before touching the database
  - Run `uv run pytest -q` across the whole suite, including the parallel agent's tests, and `uv run pytest tests/unit -q`. The unit run must be offline, with nothing skipped and in under 60 s.
  - Ensure all tests pass, and ask the user if questions arise.
  - _Requirements: 17.1_

- [ ] 10. Live run against the AWS-hosted Exasol (destructive, needs explicit user confirmation)
  - [-] 10.1 Show the target, get confirmation, then run `--apply-schema` once
    - Run `uv run python scripts/preflight.py`.
    - With a read-only query through `connect(schema="")`, print the following:
      - the Target_Database host and port from `db.settings()` (never the password) and the database version;
      - every MEDGUARD table with its row count, expecting DRUG_PRODUCT 63, PATIENT 24, PRESCRIPTION 149, DISPENSING 1043, REVIEW_QUEUE 0 and AUDIT_LOG 0;
      - any table that would be unmanaged.
    - Stop and ask the user for explicit confirmation with the `user_input` tool. Show the host, the counts, and the warning that every Canonical_Table, including CLINICIAN_REVIEW and AUDIT_LOG, is recreated empty. If the host, the counts or the table set differ from expectations, do not proceed. Report the difference instead.
    - Only after confirmation, run `uv run python src/hackathon26/seed.py --apply-schema` once. Expect the six legacy tables marked "to be dropped", nothing "unmanaged", the printed 17 counts, EVIDENCE_FOUND and exit 0.
    - _Requirements: 2.2, 2.3, 2.5, 2.7, 3.8, 13.8, 13.11_

  - [~] 10.2 Re-seed and verify
    - Run `uv run python src/hackathon26/seed.py`. The counts must match 10.1 (idempotence), and the run must end with EVIDENCE_FOUND and exit 0.
    - Run `uv run python src/hackathon26/seed.py --verify` and expect EVIDENCE_FOUND and exit 0.
    - Run `uv run python scripts/preflight.py` and expect 17 tables.
    - If any step fails, stop and report the exit code and output. Do not re-run `--apply-schema` without asking the user.
    - _Requirements: 3.5, 3.8, 13.10, 13.11_

  - [ ]\* 10.3 Run the Integration_Check against the seeded database
    - With the API stopped, run `MEDGUARD_INTEGRATION=1 uv run pytest tests/integration -q`.
    - _Requirements: 17.8, 17.9, 17.13_

- [ ] 11. Docstring and PROJECT.md status
  - [~] 11.1 Write the Seed_Command module docstring test-first
    - Add a test to `tests/unit/test_seed_cli.py` first. The docstring must contain the following:
      - the four exact command lines (`seed.py`, `seed.py --apply-schema`, `seed.py --verify`, `scripts/fetch_labels.py`);
      - that Schema_Apply drops the Legacy_Tables and recreates every Canonical_Table empty, App_Written_Tables included;
      - that Verify_Mode writes no rows;
      - that only the Label_Fetcher contacts openFDA;
      - `--reset` only as a retired option.
    - Then write the docstring in `src/hackathon26/seed.py`.
    - _Requirements: 15.5_

  - [~] 11.2 Update the PROJECT.md status list
    - Make this change only after the unit tests pass (task 9) and a live seed run ended with EVIDENCE_FOUND (task 10).
    - Mark "Seed data" and "FDA label ingestion" as done, and change the schema item from 16 to 17 tables.
    - Leave every other status item and paragraph unchanged, including the teammate's listener/resolution note. PROJECT.md has uncommitted edits by others, so edit only those lines.
    - _Requirements: 15.6_

- [~] 12. Final checkpoint: ensure the whole suite passes
  - Run `uv run pytest -q` across the whole suite, including the parallel agent's tests.
  - Ensure all tests pass, and ask the user if questions arise.
  - _Requirements: 17.1_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. The Quote_Verifier property tests
  in 1.4 are required, because Requirement 17.2 makes them mandatory.
- Requirement 1.9 (Match_Level single source) is only fully met once the resolution owner imports the codes
  from `match_level.py`. Task 1.3 records this as a strict xfail and does not edit `resolution/`.
- Design gaps 1–5 (Reference_Range_Flag computed in Python, exception-based statuses, stricter `verify_rows`,
  the IS_SYNTHETIC patient filter) stay with the evidence-check owner. Task 6.1 adapts to the current
  behaviour and does not edit `evidence_check/`.
- Requirements 12.1–12.7 and 12.12 describe the existing `EVIDENCE_JOIN_QUERY`. Its owner covers them with
  `tests/integration/test_evidence_sql.py`. This plan adds no second query. The seeded results for 12.8–12.11
  are asserted in the optional task 8.5.
- Task 10 changes shared infrastructure. It must stop for user confirmation before `--apply-schema` and must
  not widen security groups or change AWS resources. If the venue IP blocks access, report it to the user.
- Stop the API while seeding. Exasol's serializable transactions can make the seed wait or roll back.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.5", "1.6", "2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3"] },
    { "id": 4, "tasks": ["2.4"] },
    { "id": 5, "tasks": ["3.1"] },
    { "id": 6, "tasks": ["3.2", "5.1"] },
    { "id": 7, "tasks": ["3.3", "5.2", "6.1"] },
    { "id": 8, "tasks": ["5.3"] },
    { "id": 9, "tasks": ["5.4"] },
    { "id": 10, "tasks": ["5.5", "5.7", "8.1"] },
    { "id": 11, "tasks": ["5.6", "8.2"] },
    { "id": 12, "tasks": ["8.3"] },
    { "id": 13, "tasks": ["8.4", "8.5"] },
    { "id": 14, "tasks": ["10.1"] },
    { "id": 15, "tasks": ["10.2"] },
    { "id": 16, "tasks": ["10.3", "11.1"] },
    { "id": 17, "tasks": ["11.2"] }
  ]
}
```
