# Requirements Document

## Introduction

MedGuard is a hackathon demo (Healthcare Hackathon Bayern, demo on 14 Nov 2026). It follows a scripted
heart-failure consultation, resolves vague pill descriptions against the patient's own medication list,
checks interactions against verbatim FDA package-insert text, and joins the patient's own lab results in
Exasol. This feature delivers only the data layer that the later backend, Bedrock synthesis and UI specs
depend on:

1. Apply the canonical schema `sql/01_schema.sql`, with a few small adjustments that bring it to 17 tables,
   to the `MEDGUARD` schema of the Exasol instance that `src/hackathon26/db.py` resolves (for this event an
   AWS-hosted Exasol 2026.1.0), replacing six legacy tables.
2. Seed one deterministic synthetic heart-failure patient (72F) with medications, pill appearances, dated
   labs and the scripted consultation.
3. Fetch openFDA drug-label JSON for the demo drugs into committed snapshots under `data/reference/`, and
   import the exact section text with provenance.
4. Seed drug, class, synonym and curated risk-rule reference data. Each rule is traceable to a stored label
   section and a code-verified verbatim quote.
5. Prove the core Exasol join: one parameterized query returns the triple-whammy evidence for this patient,
   and code confirms that the quote is a contiguous substring of the stored section text.

### Decisions already made by the user

- The six legacy tables from the old `src/hackathon26/seed.py` may be dropped: DRUG_PRODUCT (63 rows),
  PATIENT (24), PRESCRIPTION (149), DISPENSING (1043), REVIEW_QUEUE (0) and AUDIT_LOG (0). All are synthetic.
  The old six-table DDL is retired so nobody re-runs it against the new schema.
- Hackathon-sized: one DDL file plus one idempotent seed command. No migration framework, no migration
  ledger, no disposable test schemas.
- Confidence is expressed as named Match_Level codes, not uncalibrated percentages.
- Small schema adjustments are allowed where the demo needs them. Requirement 1 lists every adjustment.

### Out of scope

The FastAPI backend, mention detection and resolution logic, the rules engine that writes FINDING rows and
assigns a severity, Bedrock synthesis and Guardrails, and the UI. The seed does not write DRUG_MENTION,
MENTION_CANDIDATE, FINDING, CLINICIAN_REVIEW or AUDIT_LOG.

### Facts checked while writing these requirements

- openFDA set id `01da05d8-e72e-4208-bf92-a5cd929f15ab` (the ramipril label cited in `web/prototype.html`) was
  fetched from `api.fda.gov` on 13 Nov 2026. The label is a human prescription drug label, effective
  2022-07-01 (version 6), with `openfda.pharm_class_epc` "Angiotensin Converting Enzyme Inhibitor [EPC]".
  Element 0 of its `drug_interactions` field contains the triple-whammy sentence quoted in Requirement 10,
  and element 0 of its `warnings_and_cautions` field contains the hyperkalemia passage quoted in
  Requirement 10.
- The first request returned HTTP 429 "Too Many Requests" and a retry after 8 seconds succeeded. This is why
  Requirement 7 includes retry behaviour and why the seed reads committed snapshots instead of the network.

### Notes for later specs

- The lab values are synthetic fixture values chosen for the story. They are not clinical thresholds. The
  creatinine values (0.97 → 1.07 → 1.20 mg/dL) are chosen to be consistent with the eGFR values for a
  72-year-old woman under CKD-EPI 2021. The UI prototype currently shows 0.90 → 1.24 and should align.
- The pill appearances are invented for the synthetic patient (ramipril white and round). The real NLM
  photos in `web/img/pills/` show ramipril 5 mg as a red capsule, so the UI should not pair those photos
  with this patient's appearance rows.
- The UI prototype shows numeric confidence (0.52, 0.41, 0.62). The Match_Level decision replaces these.
- A teammate has already built a listener (`src/hackathon26/listener/`) and read-only resolution
  (`src/hackathon26/resolution/`) against the canonical tables. That resolution code reads
  PATIENT_MEDICATION, DRUG and DRUG_APPEARANCE (COLOR, SHAPE, IMPRINT, STRENGTH, MANUFACTURER, SRC_NAME)
  with a numeric PATIENT_ID and requires DRUG_APPEARANCE.STRENGTH to equal PATIENT_MEDICATION.STRENGTH as
  text. Requirement 4 criterion 5 keeps that compatible; do not rename those columns.
- The listener vocabulary currently recognises only the shapes "round" and "oval". The Demo_Script says
  "the long white one" and furosemide's SHAPE is 'oblong', so the listener needs a "long" → 'oblong'
  mapping before step 1 of the demo can separate the two white tablets.
- The Demo_Script intentionally differs from `web/prototype.html`: the prototype's SEQ 6 says
  "something for it" and its SEQ 8 names no product. The UI spec should follow the Demo_Script. Phrasing
  SEQ 8 with some uncertainty (for example "I think the box says ibuprofen") keeps the doctor's
  "bring the box" follow-up meaningful.
- `sql/01_schema.sql` line 171 has a comment containing a semicolon. Schema_Apply must not split statements
  naively on ";".
- The SECTION_TYPE column comment in `sql/01_schema.sql` omits `warnings_and_cautions`; update the comment
  (no type change needed).

## Glossary

- **Target_Database**: The Exasol instance that `connect()` in `src/hackathon26/db.py` resolves from `.env`
  and the deployment files.
- **MEDGUARD_Schema**: The schema named `MEDGUARD` in the Target_Database.
- **Schema_File**: `sql/01_schema.sql`, the single DDL file for the MEDGUARD_Schema.
- **Canonical_Table**: A table defined in the Schema_File, including the adjustments in Requirement 1. There
  are 17 Canonical_Tables: the 16 original tables plus RISK_RULE_CLASS.
- **Legacy_Table**: One of the six tables created by the old seed script: DRUG_PRODUCT, PRESCRIPTION,
  DISPENSING, REVIEW_QUEUE, PATIENT in the legacy layout (VARCHAR PATIENT_ID and a LANGUAGE column) and
  AUDIT_LOG in the legacy layout (EVENT_ID, ACTOR and EVENT_ACTION columns).
- **Seed_Command**: The single command `uv run python src/hackathon26/seed.py` that loads all seed data.
- **Schema_Apply**: The explicit, destructive mode of the Seed_Command, selected by a dedicated command-line
  option (proposed name `--apply-schema`), that drops Legacy_Tables and executes the Schema_File.
- **Verify_Mode**: The read-only mode of the Seed_Command, selected by a dedicated command-line option
  (proposed name `--verify`), that runs the Join_Verification without writing rows.
- **Default_Seed_Run**: An invocation of the Seed_Command without the Verify_Mode option, either alone or
  after Schema_Apply in the same invocation. A Default_Seed_Run writes rows only to Seed_Owned_Tables and
  executes no DDL.
- **Seed_Owned_Table**: One of DRUG, DRUG_CLASS, CLASS_SYNONYM, DRUG_LABEL_SECTION, DRUG_APPEARANCE, PATIENT,
  PATIENT_MEDICATION, LAB_RESULT, RISK_LAB_RULE, RISK_RULE_CLASS, CONSULTATION and UTTERANCE. The
  Seed_Command owns the full contents of these tables.
- **App_Written_Table**: One of DRUG_MENTION, MENTION_CANDIDATE, FINDING, CLINICIAN_REVIEW and AUDIT_LOG.
  Later specs write these tables.
- **Demo_Fixture**: The version-controlled definition of the Demo_Patient, medications, appearances, labs,
  Demo_Script, drugs, classes, synonyms and Risk_Rules that the Seed_Command loads.
- **Demo_Patient**: The single synthetic heart-failure patient, a 72-year-old woman, displayed as
  'Patient A (72F)'.
- **Demo_Consultation**: The CONSULTATION row for the scripted follow-up of the Demo_Patient on 2026-11-13.
- **Demo_Script**: The UTTERANCE rows of the Demo_Consultation.
- **Demo_Drugs**: Ramipril, metoprolol succinate, furosemide and ibuprofen.
- **Optional_Drugs**: Spironolactone and potassium chloride. Included only when listed in the Label_Manifest.
- **Label_Manifest**: A version-controlled file under `data/reference/` that lists each drug to fetch with
  its generic name and one pinned openFDA set id.
- **Label_Fetcher**: The explicit network command that downloads openFDA label JSON for each Label_Manifest
  entry. Separate from the Seed_Command.
- **Label_Snapshot**: The raw openFDA response body for one Label_Manifest entry, saved under
  `data/reference/` and committed to the repository.
- **Snapshot_Metadata**: For each Label_Snapshot, the request URL, the UTC fetch timestamp and the SHA-256 of
  the snapshot file.
- **Label_Importer**: The part of the Seed_Command that converts Label_Snapshots into DRUG_LABEL_SECTION rows.
- **Imported_Section_Field**: One of the openFDA label fields `boxed_warning`, `contraindications`,
  `warnings`, `warnings_and_cautions` and `drug_interactions`.
- **Content_Hash**: The lowercase hexadecimal SHA-256 of the UTF-8 bytes of a SECTION_TEXT value.
- **Risk_Rule**: A curated RISK_LAB_RULE row with its required drug classes, one governing analyte, a
  direction, a linked evidence section and an Evidence_Quote.
- **Triple_Whammy_Rule**: The Risk_Rule rows for NSAID + ACE inhibitor + loop diuretic leading to acute kidney
  injury risk, with one row per governing analyte (EGFR and CREATININE).
- **Potassium_Rule**: The Risk_Rule row for an ACE inhibitor governed by POTASSIUM.
- **Evidence_Quote**: Curated text that must be a contiguous, case-sensitive substring of the SECTION_TEXT of
  the linked DRUG_LABEL_SECTION row.
- **Quote_Verifier**: The pure function that decides whether a quote is a contiguous, case-sensitive
  substring of a section text.
- **As_Of_Date**: The reference date that decides which medications are current and which labs are recent.
  For the demo, the Demo_Consultation date 2026-11-13.
- **Evidence_Join_Query**: The single parameterized SQL statement that joins the candidate's classes, the
  patient's current medications, the Risk_Rules, the linked label sections and the patient's lab results.
- **Join_Verification**: The routine that runs the Evidence_Join_Query, checks quotes and hashes in Python
  and reports one Join_Status.
- **Join_Status**: One of EVIDENCE_FOUND, NO_DOCUMENTED_INTERACTION_FOUND, EVIDENCE_UNVERIFIED,
  UNKNOWN_PATIENT, UNKNOWN_CANDIDATE and QUERY_FAILED. UNKNOWN_CANDIDATE means the candidate is missing, is
  given twice (both as a DRUG_ID and as a CLASS_NAME), or matches no DRUG_CLASS row.
- **Match_Level**: The named confidence vocabulary, ranked from strongest to weakest: NAME_MATCH
  ("name match"), COLOUR_SHAPE_MATCH ("colour + shape match"), COLOUR_MATCH ("colour match"),
  CLASS_INFERRED ("class inferred") and UNRESOLVED ("unresolved").
- **Reference_Range_Flag**: TRUE when a LAB_RESULT VALUE_NUM is below REF_LOW or above REF_HIGH, otherwise
  FALSE.
- **Curated_Text**: Every text value the team authors in the Demo_Fixture: utterances, display names, the
  clinician label, the scenario name, appearance source text, class synonyms, rule names and rationales.
  Curated_Text excludes openFDA label text, Evidence_Quotes and the record fields PRIMARY_DX, STRENGTH and
  SCHEDULE_TEXT.
- **Banned_Phrase_List**: The committed test list of phrases, in four categories (dose change, starting or
  stopping a medicine, diagnosis statement, prescribing recommendation), that Curated_Text other than
  utterances must not contain.
- **Unit_Tests**: The pytest tests under `tests/unit/` that need neither network nor database access.
- **Integration_Check**: The opt-in pytest tests under `tests/integration/` that run against the
  Target_Database when the environment variable `MEDGUARD_INTEGRATION` is set to `1`.

## Requirements

### Requirement 1: Minimal schema adjustments

**User Story:** As a developer building the later MedGuard specs, I want the canonical schema to hold
everything the demo must show, so that later specs do not need to change tables during the event.

#### Acceptance Criteria

1. THE Schema_File SHALL define on DRUG_LABEL_SECTION a column CONTENT_SHA256 of type CHAR(64) with a
   NOT NULL constraint, for holding the Content_Hash of SECTION_TEXT.
2. THE Schema_File SHALL define a rule-class table named RISK_RULE_CLASS. It SHALL have a RULE_ID column of
   type DECIMAL(10,0) holding a RISK_LAB_RULE.RULE_ID value and a CLASS_NAME column of type VARCHAR(200)
   holding a DRUG_CLASS.CLASS_NAME value, both NOT NULL, with a primary key on the pair (RULE_ID,
   CLASS_NAME). One Risk_Rule can then require two or more classes but cannot list the same class twice.
3. THE Schema_File SHALL define on RISK_LAB_RULE a column EVIDENCE_SECTION_ID of type DECIMAL(10,0) holding
   the SECTION_ID of the supporting DRUG_LABEL_SECTION row, and a column EVIDENCE_QUOTE of type
   VARCHAR(4000) holding the Evidence_Quote. Both columns SHALL have a NOT NULL constraint, and neither
   SHALL have a FOREIGN KEY constraint.
4. THE Schema_File SHALL define a MATCH_LEVEL column of type VARCHAR(30) with a NOT NULL constraint on each
   of DRUG_MENTION, MENTION_CANDIDATE and FINDING. It SHALL omit the columns DRUG_MENTION.CONFIDENCE,
   MENTION_CANDIDATE.SCORE and FINDING.CONFIDENCE.
5. THE Schema_File SHALL define on DRUG_MENTION a nullable RESOLVED_CLASS_NAME column of type VARCHAR(200),
   for holding a DRUG_CLASS.CLASS_NAME value inferred from an indication when RESOLVED_DRUG_ID is null.
6. THE Schema_File SHALL put an SQL line comment (`--`) beside each table and column added in criteria 1 to
   5, either on the same line or on the lines directly above. The comment SHALL state the reason for the
   addition, and for each MATCH_LEVEL column it SHALL name the numeric column that MATCH_LEVEL replaces.
7. THE Schema_File SHALL list, in the comment beside each MATCH_LEVEL column, all five Match_Level codes
   spelled as in the Glossary and in rank order from strongest to weakest. The comment beside
   FINDING.MATCH_LEVEL SHALL also state two things. FINDING.MATCH_LEVEL records the Match_Level of the
   mention that identified FINDING.TRIGGER_DRUG_ID. FINDING.MATCH_BASIS separately records how the label
   evidence was matched.
8. THE Schema_File SHALL keep every column that criteria 1 to 5 do not add or remove the same as in the
   16-table Schema_File on `main` before this feature: name, data type, NOT NULL constraint, DEFAULT value
   and PRIMARY KEY membership.
9. THE Match_Level vocabulary SHALL be defined in exactly one Python module under `src/hackathon26/`. The
   module SHALL map each of the five codes, spelled as in the Glossary, to a rank from 1 (NAME_MATCH,
   strongest) to 5 (UNRESOLVED, weakest) and to the plain-language label quoted for it in the Glossary.
   Every other module under `src/hackathon26/` that uses a Match_Level code SHALL import it from that
   module.
10. IF a caller asks the Match_Level vocabulary for the rank or label of a value that is not exactly one of
    the five codes, including a value that differs only in letter case or surrounding whitespace, THEN THE
    Match_Level vocabulary SHALL raise an error that names the value.
11. THE Schema_File SHALL define exactly 17 tables: the 12 Seed_Owned_Tables and the 5 App_Written_Tables.

### Requirement 2: Apply the canonical schema

**User Story:** As the developer preparing the demo database, I want one explicit command that replaces the
legacy tables with the canonical schema, so that the MEDGUARD_Schema holds exactly the tables later specs
expect.

#### Acceptance Criteria

1. THE Seed_Command SHALL execute DROP, CREATE and ALTER statements only in an invocation where the operator
   supplies the Schema_Apply option on the command line.
2. WHEN Schema_Apply starts, THE Seed_Command SHALL print the Target_Database host, port and database version
   and the MEDGUARD_Schema name before executing any DROP or CREATE statement.
3. WHEN Schema_Apply starts, THE Seed_Command SHALL print the name and row count of each Legacy_Table and each
   Canonical_Table already present in the MEDGUARD_Schema before executing any DROP or CREATE statement. Each
   Legacy_Table SHALL be marked as to be dropped, and each Canonical_Table as to be replaced empty.
4. WHEN Schema_Apply runs, THE Seed_Command SHALL drop each Legacy_Table present in the MEDGUARD_Schema and
   then execute each statement of the Schema_File in file order.
5. WHEN Schema_Apply has executed every statement of criterion 4 without a database error, THE MEDGUARD_Schema
   SHALL meet all three of these conditions:
   - It contains every Canonical_Table with exactly the column names defined in the Schema_File. Each column
     has the base data type defined there, meaning the type name without length, precision, scale or
     character set.
   - It contains no table named DRUG_PRODUCT, PRESCRIPTION, DISPENSING or REVIEW_QUEUE.
   - Every App_Written_Table holds zero rows.
6. IF the MEDGUARD_Schema contains a table whose name is neither the name of a Canonical_Table nor
   DRUG_PRODUCT, PRESCRIPTION, DISPENSING or REVIEW_QUEUE, THEN THE Seed_Command SHALL leave that table and
   its rows unchanged during Schema_Apply and print its name as unmanaged before executing any DROP or CREATE
   statement.
7. WHEN Schema_Apply has executed every statement of criterion 4 without a database error, THE Seed_Command
   SHALL run the default seed run in the same invocation.
8. IF a DROP statement or a Schema_File statement fails during Schema_Apply, THEN THE Seed_Command SHALL:
   - execute no further statement and skip the default seed run;
   - print the name of the table the failed statement targets, or the statement text when it targets no
     table, together with the database error message;
   - print a message saying that statements executed before the failure stay applied;
   - exit with a non-zero status.
9. WHEN Schema_Apply runs after an earlier Schema_Apply that either completed or stopped under criterion 8,
   and the cause of any earlier failure has been removed, THE Seed_Command SHALL complete Schema_Apply and
   meet criterion 5 without any manual change to the MEDGUARD_Schema.
10. IF the operator supplies the Schema_Apply option together with the Verify_Mode option, THEN THE
    Seed_Command SHALL exit with a non-zero status without connecting to the Target_Database and print an
    error message saying that the two options cannot be combined.

### Requirement 3: Idempotent default seed run

**User Story:** As a team member rehearsing the demo, I want to re-run the seed at any time and get the same
database state, so that the demo behaves identically on every run.

#### Acceptance Criteria

1. WHEN a Default_Seed_Run starts, THE Seed_Command SHALL check, before writing any row, that
   each Canonical_Table exists in the MEDGUARD_Schema with exactly the set of column names defined in the
   Schema_File. Column order is not compared, and tables that are not Canonical_Tables do not affect the
   check.
2. IF the MEDGUARD_Schema does not exist, a Canonical_Table is missing, or a Canonical_Table lacks a column
   defined in the Schema_File or has a column the Schema_File does not define, THEN THE Seed_Command SHALL
   write no row, print each mismatched table name with its missing and unexpected column names and the name
   of the Schema_Apply option, and exit with a non-zero status.
3. WHEN a Default_Seed_Run passes the check in criterion 1, THE Seed_Command SHALL replace the contents of
   every Seed_Owned_Table so that each one holds exactly the rows derived from the Demo_Fixture, the
   Label_Manifest, the Label_Snapshots and the Snapshot_Metadata, and no other row. This includes removing
   rows added by hand before the run. The Seed_Command SHALL do this without creating, altering or dropping
   any database object.
4. THE Seed_Command SHALL give each seeded row the same primary key value on every Default_Seed_Run with
   byte-identical Demo_Fixture, Label_Manifest, Label_Snapshots and Snapshot_Metadata files. This applies to
   every Seed_Owned_Table that defines a primary key in the Schema_File.
5. WHEN two Default_Seed_Runs execute in succession with byte-identical Demo_Fixture, Label_Manifest,
   Label_Snapshots and Snapshot_Metadata files and no other write to the MEDGUARD_Schema between them, THE
   MEDGUARD_Schema SHALL hold the same state after the second run as after the first. The same state means
   the same row count in every Canonical_Table and, in every Seed_Owned_Table, the same rows with equal
   values in every column, ignoring row order.
6. WHILE a Default_Seed_Run executes, including one that follows Schema_Apply, THE Seed_Command SHALL
   insert, update or delete no row of any App_Written_Table.
7. IF a database statement fails, or the storage round trip in Requirement 8 criterion 10 finds a mismatch,
   before a Default_Seed_Run commits its row changes, THEN THE Seed_Command SHALL roll back every row change
   of that run, so that every Seed_Owned_Table holds the rows it held before the run. It SHALL then print the
   affected table name with the database error message or the mismatching SECTION_ID, and exit with a
   non-zero status. Tables created by a Schema_Apply earlier in the same invocation SHALL stay in place.
8. WHEN a Default_Seed_Run commits its row changes, THE Seed_Command SHALL print the name and row count of
   each Canonical_Table, including the App_Written_Tables.
9. THE Seed_Command SHALL take every DATE and TIMESTAMP value it writes from the Demo_Fixture, the
   Label_Snapshots (label effective dates) or the Snapshot_Metadata (fetch timestamps). It SHALL store each
   value without time-zone conversion, so that the written values are the same whatever the clock time and
   time zone of the machine that runs the Seed_Command.
10. THE Seed_Command SHALL, in every mode, open network connections only to the Target_Database host and
    port, and SHALL send no request to openFDA or any other host.
11. IF the Seed_Command cannot open a connection to the Target_Database within 30 seconds, THEN THE
    Seed_Command SHALL write no row, print the Target_Database host and port and the connection error
    message without any credential value, and exit with a non-zero status.

### Requirement 4: Synthetic demo patient, medications and pill appearances

**User Story:** As the clinician in the demo, I want the patient's own medication list to record what each
tablet looks like, so that MedGuard can match "the white one" and "the small yellow one" against her
medicines and show when a description fits more than one.

#### Acceptance Criteria

1. THE Seed_Command SHALL store exactly one PATIENT row, the Demo_Patient, with DISPLAY_NAME
   'Patient A (72F)', BIRTH_YEAR 1954, SEX 'F', PRIMARY_DX 'Chronic heart failure (HFrEF)' and
   IS_SYNTHETIC TRUE, so that PATIENT holds no other row after a seed run.
2. THE Seed_Command SHALL set IS_SYNTHETIC to TRUE on every PATIENT row.
3. THE Seed_Command SHALL store exactly three PATIENT_MEDICATION rows, all for the Demo_Patient. Each row
   SHALL have STOPPED_ON null, a non-null STARTED_ON before 2026-05-14 and a DRUG_ID that references the DRUG
   row of the named drug: ramipril with STRENGTH '5 mg' and SCHEDULE_TEXT 'once in the morning',
   metoprolol succinate with STRENGTH '47.5 mg' and SCHEDULE_TEXT 'with breakfast', and furosemide with
   STRENGTH '40 mg' and SCHEDULE_TEXT 'once in the morning'.
4. THE Seed_Command SHALL store ibuprofen as a DRUG row with IS_OTC TRUE, store the DRUG rows of ramipril,
   metoprolol succinate and furosemide with IS_OTC FALSE, and store no PATIENT_MEDICATION row that
   references ibuprofen. This way ibuprofen exists in the reference data and is absent from her recorded
   medication list.
5. THE Seed_Command SHALL store exactly three DRUG_APPEARANCE rows, one for each medication of the
   Demo_Patient that is current at the As_Of_Date: ramipril with COLOR 'white' and SHAPE 'round',
   metoprolol succinate with COLOR 'yellow' and SHAPE 'oval', and furosemide with COLOR 'white' and SHAPE
   'oblong'. Each row SHALL have STRENGTH equal to the STRENGTH of that drug's PATIENT_MEDICATION row and
   IMPRINT null, so that no drug outside her medication list, ibuprofen included, has an appearance row.
6. THE Demo_Fixture SHALL give COLOR 'white' to exactly two of the Demo_Patient's current medications
   (ramipril and furosemide), COLOR 'yellow' to exactly one (metoprolol succinate), and the same
   SCHEDULE_TEXT to ramipril and furosemide. This way "the white one in the morning" fits two medications
   and "the small yellow one" fits one.
7. THE Demo_Fixture SHALL give ramipril and furosemide different, non-null SHAPE values, so that a colour
   plus shape description such as "the long white one" separates the two white tablets.
8. THE Seed_Command SHALL set SRC_NAME on every DRUG_APPEARANCE row to a value that contains the word
   'synthetic', compared case-insensitively.
9. THE Seed_Command SHALL set MANUFACTURER on every DRUG_APPEARANCE row to a fictional company name from
   the Demo_Fixture that differs, compared case-insensitively, from every `openfda.manufacturer_name`
   value in the Label_Snapshots.
10. IF a PATIENT_MEDICATION or DRUG_APPEARANCE entry in the Demo_Fixture names a drug that has no DRUG row
    in the same seed run, THEN THE Seed_Command SHALL exit with a non-zero status before writing any row
    and print the drug name.

### Requirement 5: Dated lab results

**User Story:** As the clinician in the demo, I want the patient's own dated kidney and potassium results,
so that a warning reflects her values and their trend rather than drugs in general.

#### Acceptance Criteria

1. THE Seed_Command SHALL store exactly three LAB_RESULT rows with ANALYTE 'EGFR' for the Demo_Patient, each
   with UNIT 'mL/min/1.73m2', REF_LOW 60 and REF_HIGH null: VALUE_NUM 62 measured on 2026-05-14, 55 measured
   on 2026-07-16 and 48 measured on 2026-10-12.
2. THE Seed_Command SHALL store exactly three LAB_RESULT rows with ANALYTE 'POTASSIUM' for the Demo_Patient,
   each with UNIT 'mmol/L', REF_LOW 3.5 and REF_HIGH 5.0: VALUE_NUM 4.6 measured on 2026-05-14, 4.9 measured
   on 2026-07-16 and 5.1 measured on 2026-10-12.
3. THE Seed_Command SHALL store exactly three LAB_RESULT rows with ANALYTE 'CREATININE' for the Demo_Patient,
   each with UNIT 'mg/dL', REF_LOW 0.50 and REF_HIGH 1.10: VALUE_NUM 0.97 measured on 2026-05-14, 1.07
   measured on 2026-07-16 and 1.20 measured on 2026-10-12.
4. THE Demo_Fixture SHALL give every LAB_RESULT row a non-null VALUE_NUM, UNIT and MEASURED_AT, at least one
   non-null value among REF_LOW and REF_HIGH, and a REF_LOW lower than REF_HIGH wherever both are non-null.
5. THE Demo_Fixture SHALL date every LAB_RESULT row on or before the As_Of_Date 2026-11-13 and fewer than
   365 days before it, so that the Evidence_Join_Query in Requirement 12 returns every seeded result.
6. THE Demo_Fixture SHALL give the results of each analyte distinct MEASURED_AT dates such that, in
   MEASURED_AT order, each EGFR value is lower than the previous EGFR value and each POTASSIUM and CREATININE
   value is higher than the previous value of the same analyte.
7. THE Seed_Command SHALL store no LAB_RESULT rows other than the nine rows defined in criteria 1 to 3.
8. THE Demo_Fixture SHALL give the earliest result of each analyte a Reference_Range_Flag of FALSE and the
   latest result of each analyte a Reference_Range_Flag of TRUE, so that each trend moves from inside to
   outside its stored reference range.

### Requirement 6: Scripted consultation

**User Story:** As the presenter, I want the consultation script stored in Exasol with replay order and
timing, so that the UI replays the same 90-second conversation every time.

#### Acceptance Criteria

1. THE Seed_Command SHALL store exactly one CONSULTATION row, with PATIENT_ID equal to the PATIENT_ID of the
   Demo_Patient, STARTED_AT 2026-11-13 09:00:00, CLINICIAN 'Dr. Vogel' (the fictional clinician named in the
   audit text of `web/prototype.html`) and SCENARIO 'hf-follow-up-v1'.
2. THE Demo_Script SHALL consist of exactly 10 UTTERANCE rows that carry the CONSULT_ID of the
   Demo_Consultation. Every odd SEQ SHALL have SPEAKER 'DOCTOR' and every even SEQ SHALL have SPEAKER
   'PATIENT', which matches the speaker order of the SCRIPT array in `web/prototype.html`.
3. THE Demo_Script SHALL contain the exact phrases "the white one" and "the small yellow one" in the PATIENT
   utterance with SEQ 2, and the exact phrase "the long white one" in the PATIENT utterance with SEQ 4. Each
   phrase SHALL match as a contiguous, case-sensitive substring of UTTERANCE_TEXT.
4. THE Demo_Script SHALL contain the exact phrase "something for my knee" in the PATIENT utterance with
   SEQ 6, matched as a contiguous, case-sensitive substring of UTTERANCE_TEXT.
5. THE Demo_Script SHALL contain the word "ibuprofen", matched as a whole word and case-insensitively, in the
   PATIENT utterance with SEQ 8 and in no other utterance. No UTTERANCE_TEXT SHALL contain "ramipril",
   "metoprolol" or "furosemide", matched case-insensitively.
6. THE Demo_Script SHALL number its utterances with the consecutive integer SEQ values 1 to 10, with each
   value used exactly once.
7. THE Demo_Script SHALL give every utterance a non-null integer OFFSET_MS, in milliseconds after the
   STARTED_AT of the Demo_Consultation. OFFSET_MS SHALL be 0 at SEQ 1, at least 2000 greater than the
   previous utterance's OFFSET_MS at each later SEQ, and at most 90000 at SEQ 10.
8. THE Demo_Script SHALL use only the SPEAKER values 'DOCTOR' and 'PATIENT'.
9. THE Demo_Script SHALL contain the following contiguous, case-sensitive substrings, which anchor the topics
   of the SCRIPT array in `web/prototype.html`: "Good morning" in the DOCTOR utterance with SEQ 1, "water
   tablet" in the DOCTOR utterance with SEQ 3, "dizzy" in the PATIENT utterance with SEQ 4, and "bring the
   box" in the DOCTOR utterance with SEQ 9.
10. THE Demo_Script SHALL give every utterance an UTTERANCE_TEXT of 1 to 4000 characters that contains at
    least one non-whitespace character.
11. THE Demo_Script SHALL contain, in addition to passing the Curated_Text checks of Requirement 14 criteria 1
    and 2, no digit and none of the whole words or phrases "mg", "milligram", "milligrams", "once a day",
    "twice a day" and "times a day" (compared case-insensitively) in any UTTERANCE_TEXT.

### Requirement 7: Label manifest, fetch and snapshots

**User Story:** As the developer, I want FDA label JSON fetched once into committed snapshots, so that
seeding and the demo work without network and quote the same document every time.

#### Acceptance Criteria

1. THE Label_Manifest SHALL contain exactly one entry for each Demo_Drug, at most one entry for each
   Optional_Drug and no other entries, each entry giving the generic name that the Demo_Fixture uses for that
   drug and one pinned openFDA set id written as a lowercase 8-4-4-4-12 hexadecimal identifier.
2. THE Label_Manifest SHALL pin ramipril to openFDA set id `01da05d8-e72e-4208-bf92-a5cd929f15ab`.
3. WHERE an Optional_Drug is listed in the Label_Manifest, THE Label_Fetcher SHALL request, validate, save
   and report the label of that Optional_Drug under criteria 4 to 9, exactly as for a Demo_Drug.
4. WHEN the Label_Fetcher runs, THE Label_Fetcher SHALL send one request per Label_Manifest entry, in
   manifest order, to `https://api.fda.gov/drug/label.json` with a single query parameter: a search that
   matches the `set_id` field exactly against that entry's pinned set id.
5. WHEN openFDA answers with HTTP 200 and a JSON body in which `meta.results.total` equals 1, the `results`
   list holds exactly one label, that label's `set_id` equals the pinned set id, and at least one element of
   that label's `openfda.generic_name` contains the entry's generic name (case-insensitive comparison), THE
   Label_Fetcher SHALL save the response body byte-for-byte as the Label_Snapshot of that entry under
   `data/reference/`.
6. WHEN the Label_Fetcher saves a Label_Snapshot, THE Label_Fetcher SHALL write that entry's
   Snapshot_Metadata with the full request URL as sent, the UTC fetch timestamp at second precision and the
   lowercase hexadecimal SHA-256 of the saved file's bytes, and print the entry's generic name and that
   SHA-256.
7. THE Label_Fetcher SHALL leave at least 1 second between the starts of any two consecutive openFDA
   requests, retries included.
8. IF openFDA returns HTTP 429, THEN THE Label_Fetcher SHALL wait at least 5 seconds and repeat the same
   request, with at most 3 repeats per entry (at most 4 attempts in total).
9. IF any of the following occurs for an entry: the last permitted attempt returns HTTP 429, a request
   returns a status other than 200 or 429, a request runs longer than 30 seconds or cannot connect, the body
   is not valid JSON, openFDA reports no match (HTTP 404 or zero results), or the response fails any check in
   criterion 5, THEN THE Label_Fetcher SHALL do all of the following:
   - not retry the request, except for HTTP 429 under criterion 8;
   - keep that entry's existing Label_Snapshot and Snapshot_Metadata unchanged, and create neither if the
     entry had none;
   - continue with the remaining entries;
   - exit with a non-zero status, printing every failed entry with its failure reason.
10. FOR ALL Snapshot_Metadata records with a non-empty request URL, a UTC timestamp at second precision and a
    64-character lowercase hexadecimal SHA-256, writing the record to its file and reading the file back
    SHALL produce an equal record (round-trip property).
11. THE Label_Fetcher SHALL write files only to paths under `data/reference/` that `.gitignore` does not
    exclude, and SHALL run without connecting to the Target_Database.
12. THE Label_Fetcher SHALL send every request without an API key.
13. IF the Label_Manifest lacks an entry for a Demo_Drug, lists one drug more than once, lists a drug that is
    neither a Demo_Drug nor an Optional_Drug, or gives a set id that does not match the form in criterion 1,
    THEN THE Label_Fetcher SHALL exit with a non-zero status before sending any request and print the entry
    at fault.
14. WHEN the Label_Fetcher has saved a Label_Snapshot for every Label_Manifest entry, THE Label_Fetcher SHALL
    exit with status zero.

### Requirement 8: Label import with provenance

**User Story:** As the clinician, I want every stored label section to carry its document id, date, source
and hash, so that any quote I see can be traced to one FDA document.

#### Acceptance Criteria

1. WHEN the Seed_Command runs, THE Label_Importer SHALL read label text only from the Label_Snapshots of the
   entries listed in the Label_Manifest and SHALL ignore every other file under `data/reference/`.
2. IF the Label_Snapshot or the Snapshot_Metadata of a Label_Manifest entry is missing, or the SHA-256 of the
   Label_Snapshot file differs from the SHA-256 recorded in its Snapshot_Metadata, THEN THE Seed_Command SHALL
   exit with a non-zero status before writing any row and print the drug name and the Label_Fetcher command.
3. WHEN the Label_Importer processes a Label_Snapshot, THE Label_Importer SHALL store one DRUG_LABEL_SECTION
   row for each string element of one or more characters in each Imported_Section_Field present in the label
   (the single element of the Label_Snapshot's `results` array). SECTION_ID values SHALL increase first with
   Label_Manifest entry order, then with the Imported_Section_Field order listed in the Glossary, then with
   the element's position in the Label_Snapshot.
4. THE Label_Importer SHALL store SECTION_TEXT exactly equal to the JSON-decoded source string element,
   without trimming, whitespace normalization, character substitution or truncation.
5. THE Label_Importer SHALL set SECTION_TYPE to the openFDA field name of the source string element, which is
   one of the five Imported_Section_Field names.
6. THE Label_Importer SHALL set the following columns on every DRUG_LABEL_SECTION row:
   - DRUG_ID to the DRUG row of the drug named in the Label_Manifest entry.
   - LABEL_SET_ID to the label's `set_id`.
   - LABEL_EFFECTIVE_AT to the date parsed from the label's `effective_time` in YYYYMMDD form.
   - SOURCE_URL to the Snapshot_Metadata request URL.
   - SOURCE_FETCHED_AT to the Snapshot_Metadata UTC fetch timestamp, stored as a UTC value without time-zone
     conversion.
   - CONTENT_SHA256 to the Content_Hash of SECTION_TEXT.

   For the ramipril label this gives LABEL_SET_ID `01da05d8-e72e-4208-bf92-a5cd929f15ab` and
   LABEL_EFFECTIVE_AT 2022-07-01.

7. IF a Label_Snapshot fails any of the following checks, THEN THE Seed_Command SHALL exit with a non-zero
   status before writing any row and print the drug name and the failed check:
   - its `results` array has exactly one element;
   - the label has a `set_id`;
   - the `set_id` equals the pinned set id of its Label_Manifest entry;
   - the `effective_time` is exactly 8 digits that form a valid calendar date in YYYYMMDD form.
8. IF an Imported_Section_Field element is an empty string of zero characters, THEN THE Label_Importer SHALL
   store no row for that element and print the drug name and field name.
9. FOR ALL imported DRUG_LABEL_SECTION rows, SECTION_TEXT SHALL equal the JSON-decoded string element at the
   same drug, field and position in the Label_Snapshot, and CONTENT_SHA256 SHALL be 64 lowercase hexadecimal
   characters equal to the Content_Hash recomputed from SECTION_TEXT (invariant).
10. WHEN the Seed_Command has written the DRUG_LABEL_SECTION rows of a run, THE Seed_Command SHALL, before
    committing the run, read every SECTION_TEXT and CONTENT_SHA256 back from the Target_Database by
    SECTION_ID. It SHALL confirm that each text read back equals the text written and that the Content_Hash of
    each text read back equals the CONTENT_SHA256 read back (storage round trip).
11. IF a SECTION_TEXT value would exceed 2,000,000 characters, or a SECTION_TYPE, LABEL_SET_ID or SOURCE_URL
    value would exceed the declared length of its column in the Schema_File, THEN THE Seed_Command SHALL exit
    with a non-zero status before writing any row and print the drug name, the column name and the value's
    character length.
12. IF the storage round trip in criterion 10 finds a missing SECTION_ID, a SECTION_TEXT that differs from the
    text written, or a CONTENT_SHA256 that does not match its text, THEN THE Seed_Command SHALL roll back all
    row changes of the run, exit with a non-zero status, and print the SECTION_ID, drug name and SECTION_TYPE.
13. IF a Label_Snapshot yields zero DRUG_LABEL_SECTION rows, THEN THE Seed_Command SHALL print the drug name
    with a statement that no label sections were imported for it, and continue the seed run.

### Requirement 9: Drug, class and synonym reference data

**User Story:** As the clinician, I want drugs linked to the classes that package inserts actually name, so
that a warning written about "ACE inhibitors" or "NSAIDs" reaches the patient's specific medicines.

#### Acceptance Criteria

1. THE Seed_Command SHALL store exactly one DRUG row for each Demo_Drug and for each Optional_Drug listed in
   the Label_Manifest. Each row SHALL have GENERIC_NAME equal to the generic name in that drug's
   Label_Manifest entry ('ramipril', 'metoprolol succinate', 'furosemide', 'ibuprofen', 'spironolactone',
   'potassium chloride'). RXCUI SHALL equal the RxNorm ingredient concept id that the Demo_Fixture records
   for that drug, or be null when the Demo_Fixture records none. IS_OTC SHALL be TRUE for ibuprofen and
   FALSE for every other drug.
2. THE Seed_Command SHALL store exactly one DRUG_CLASS row for each Demo_Drug, with CLASS_NAME
   'ACE inhibitor' for ramipril, 'beta blocker' for metoprolol succinate, 'loop diuretic' for furosemide
   and 'NSAID' for ibuprofen.
3. WHERE an Optional_Drug is listed in the Label_Manifest, THE Seed_Command SHALL store exactly one
   DRUG_CLASS row for that drug, with CLASS_NAME 'potassium-sparing diuretic' for spironolactone or
   'potassium supplement' for potassium chloride.
4. THE Seed_Command SHALL set CLASS_TYPE on every DRUG_CLASS row to the value the Demo_Fixture records for
   that row. That value SHALL be one of the codes listed in the Schema_File comment for CLASS_TYPE (EPC,
   MOA, CYP or ATC).
5. WHEN the Seed_Command builds the DRUG_CLASS rows of a drug whose Label_Snapshot has a non-empty
   `openfda.pharm_class_epc` list, THE Seed_Command SHALL set SRC_NAME on each of those rows to a value
   that contains the word 'curated' and the first element of that list, copied verbatim.
6. IF the Label_Snapshot of a drug has no `openfda.pharm_class_epc` list, or the list is empty, THEN THE
   Seed_Command SHALL set SRC_NAME on each of that drug's DRUG_CLASS rows to exactly 'curated'.
7. THE Seed_Command SHALL store exactly three CLASS_SYNONYM rows, each with a non-empty CURATED_BY:
   CLASS_NAME 'NSAID' with SYNONYM 'NSAIDs', CLASS_NAME 'ACE inhibitor' with SYNONYM 'ACE inhibitors', and
   CLASS_NAME 'loop diuretic' with SYNONYM 'diuretic therapy'.
8. THE Demo_Fixture SHALL meet at least one of the following conditions for every class that a Risk_Rule
   requires (grounding invariant): (a) the CLASS_NAME, or one of its CLASS_SYNONYM values, occurs in that
   Risk_Rule's Evidence_Quote as a case-insensitive substring; (b) the drug that owns the Risk_Rule's linked
   DRUG_LABEL_SECTION row has a DRUG_CLASS row with that CLASS_NAME.
9. THE Demo_Fixture SHALL make every class that a Risk_Rule requires exactly equal, case-sensitively, to the
   CLASS_NAME of at least one DRUG_CLASS row stored in the same seed run (referential consistency).
10. WHEN the Seed_Command stores a DRUG row, THE Seed_Command SHALL set:
    - BRAND_NAMES to the elements of the Label_Snapshot's `openfda.brand_name` list, in snapshot order,
      joined by ', ', or null when that list is absent or empty;
    - SOURCE_FETCHED_AT to the fetch timestamp in the Snapshot_Metadata of that drug's Label_Snapshot;
    - SRC_NAME to a value that contains 'openFDA' and the pinned set id of that drug's Label_Manifest entry,
      and that also contains 'RxNorm' when RXCUI is non-null.
11. IF the Label_Manifest has no entry for a Demo_Drug, THEN THE Seed_Command SHALL exit with a non-zero
    status before writing any row and print the generic name of that Demo_Drug.
12. IF the Demo_Fixture violates criterion 8 or criterion 9, THEN THE Seed_Command SHALL exit with a non-zero
    status before writing any row and print the RULE_NAME and the class name that failed the check.

### Requirement 10: Curated risk rules with evidence

**User Story:** As the clinician, I want each risk rule tied to a verbatim sentence from a real package
insert, so that MedGuard's warning is a documented statement and not a model's opinion.

#### Acceptance Criteria

1. THE Seed_Command SHALL store the Triple_Whammy_Rule as exactly two RISK_LAB_RULE rows with RULE_NAME
   'NSAID + ACE inhibitor + loop diuretic: acute kidney injury risk'. One row SHALL have ANALYTE 'EGFR' and
   DIRECTION 'LOW', and the other SHALL have ANALYTE 'CREATININE' and DIRECTION 'HIGH'.
2. THE Seed_Command SHALL relate each Triple_Whammy_Rule row, through RISK_RULE_CLASS, to exactly three
   required classes: 'NSAID', 'ACE inhibitor' and 'loop diuretic'.
3. THE Seed_Command SHALL store the Potassium_Rule as exactly one RISK_LAB_RULE row with RULE_NAME
   'ACE inhibitor: hyperkalemia risk', ANALYTE 'POTASSIUM' and DIRECTION 'HIGH'. Through RISK_RULE_CLASS,
   this row SHALL relate to exactly one required class, 'ACE inhibitor'.
4. THE Seed_Command SHALL link each Triple_Whammy_Rule row to the DRUG_LABEL_SECTION row imported from
   element 0 of the `drug_interactions` field of the ramipril Label_Snapshot (LABEL_SET_ID
   `01da05d8-e72e-4208-bf92-a5cd929f15ab`). It SHALL store as Evidence_Quote exactly the following sentence,
   where each line break in this document stands for one space: "In patients who are elderly,
   volume-depleted (including those on diuretic therapy), or with compromised renal function,
   co-administration of NSAIDs, including selective COX-2 inhibitors, with ACE inhibitors, including
   ramipril, may result in deterioration of renal function, including possible acute renal failure."
5. THE Seed_Command SHALL link the Potassium_Rule to the DRUG_LABEL_SECTION row imported from element 0 of
   the `warnings_and_cautions` field of the ramipril Label_Snapshot (LABEL_SET_ID
   `01da05d8-e72e-4208-bf92-a5cd929f15ab`). It SHALL store as Evidence_Quote exactly the following passage,
   where each line break in this document stands for one space: "Risk factors for the development of
   hyperkalemia include renal insufficiency, diabetes mellitus, and the concomitant use of potassium-sparing
   diuretics, potassium supplements, and/or potassium-containing salt substitutes".
6. IF the linked DRUG_LABEL_SECTION row of any Risk_Rule does not exist, or the Quote_Verifier returns false
   for the Evidence_Quote of that Risk_Rule against the SECTION_TEXT of the linked row, THEN THE
   Seed_Command SHALL exit with a non-zero status, leave the contents of every table as they were before the
   run, and print the RULE_NAME, LABEL_SET_ID and SECTION_TYPE of the failing Risk_Rule.
7. THE Seed_Command SHALL set CONCERN_AT to null on every Risk_Rule, so that lab values are judged only
   against the REF_LOW and REF_HIGH stored with each LAB_RESULT (the Reference_Range_Flag).
8. THE Seed_Command SHALL set SRC_NAME on every Risk_Rule to a value that contains both the LABEL_SET_ID and
   the SECTION_TYPE of the linked DRUG_LABEL_SECTION row.
9. THE Seed_Command SHALL set RATIONALE on every Risk_Rule to a non-empty Curated_Text value of at most 1000
   characters. The value SHALL name the ANALYTE of the Risk_Rule ('eGFR', 'creatinine' or 'potassium') and
   each CLASS_NAME the Risk_Rule requires, compared case-insensitively.
10. WHEN the Seed_Command completes a seed run, THE MEDGUARD_Schema SHALL hold exactly three RISK_LAB_RULE
    rows: the two Triple_Whammy_Rule rows and the Potassium_Rule row.

### Requirement 11: Quote verification

**User Story:** As the team, I want quotes checked by code against the stored text, so that no interaction
claim depends on trusting a model or a manual copy-paste.

#### Acceptance Criteria

1. THE Quote_Verifier SHALL take a quote and a section text and return true if and only if the quote
   contains at least one non-whitespace character and occurs as a contiguous, case-sensitive substring of
   the section text. It SHALL compare the exact characters given, without trimming, whitespace
   normalization, case folding, Unicode normalization or character substitution.
2. FOR ALL section texts S and all index pairs i, j with 0 ≤ i < j ≤ length(S), where S[i:j] (the
   characters of S from position i up to but excluding position j) contains at least one non-whitespace
   character, THE Quote_Verifier SHALL return true for the quote S[i:j] against S (substring property).
3. FOR ALL section texts S and quotes Q where Q does not occur as a contiguous, case-sensitive substring of S,
   THE Quote_Verifier SHALL return false (rejection property).
4. IF the quote is null, is empty or consists only of Unicode whitespace characters, or the section text is
   null, THEN THE Quote_Verifier SHALL return false without raising an error.
5. IF the quote matches a substring of the section text except for one or more of the following
   differences, THEN THE Quote_Verifier SHALL return false: added or removed leading or trailing whitespace;
   an internal space, tab or line break that is added, removed or replaced by a different whitespace
   character; a different letter case in any character; or a straight quotation mark or apostrophe in place
   of a typographic one, or the reverse.
6. THE Quote_Verifier SHALL compute its result from the quote and the section text alone, without network,
   database or file access, so that the same inputs return the same result on every call.
7. THE Seed_Command, the Join_Verification and the Unit_Tests SHALL decide whether an Evidence_Quote is
   verified only by calling the Quote_Verifier, so that Requirement 10 criterion 6, Requirement 13
   criterion 1 and Requirement 17 criterion 7 all apply the same check.

### Requirement 12: Evidence join query

**User Story:** As the clinician, I want one Exasol query to connect the candidate drug, her current
medicines, the label evidence and her labs, so that the warning I see is about her and traceable to a
document.

#### Acceptance Criteria

1. THE Evidence_Join_Query SHALL be one constant SQL text that takes the patient id, the As_Of_Date, the
   candidate DRUG_ID and the candidate CLASS_NAME only as named pyexasol query parameters. When pyexasol
   formats the statement, it escapes the string values and validates the id values as decimals. The SQL text
   SHALL contain no value inserted by string concatenation, f-strings, `str.format` or pyexasol raw (`!r`)
   placeholders.
2. THE Evidence_Join_Query SHALL treat a PATIENT_MEDICATION row as current only when STARTED_ON is non-null
   and on or before the As_Of_Date, and STOPPED_ON is null or later than the As_Of_Date. A row with
   STOPPED_ON equal to the As_Of_Date is not current.
3. THE Evidence_Join_Query SHALL return a Risk_Rule only when the candidate supplies at least one class the
   Risk_Rule requires, and the candidate together with the patient's current medications supplies every class
   the Risk_Rule requires. A DRUG_ID supplies each CLASS_NAME of its DRUG_CLASS rows. A CLASS_NAME candidate
   supplies exactly that class. Classes are compared by exact, case-sensitive CLASS_NAME equality, without
   CLASS_SYNONYM expansion.
4. WHEN a Risk_Rule matches, THE Evidence_Join_Query SHALL return in one result set one row per returned
   LAB_RESULT of that Risk_Rule (or the single row defined in criterion 12). Each row SHALL carry:
   - RULE_ID, RULE_NAME, ANALYTE and DIRECTION;
   - the GENERIC_NAME of each current medication that supplies a required class the candidate does not
     supply, with each drug listed once and no drug listed when the candidate supplies every required class;
   - the evidence SECTION_ID, SECTION_TYPE, LABEL_SET_ID, LABEL_EFFECTIVE_AT, SOURCE_URL, CONTENT_SHA256,
     SECTION_TEXT and Evidence_Quote.
5. WHEN a Risk_Rule matches, THE Evidence_Join_Query SHALL return every LAB_RESULT of the patient whose
   ANALYTE equals the ANALYTE of the Risk_Rule and whose MEASURED_AT falls from 365 days before the
   As_Of_Date to the As_Of_Date, both inclusive. Each such row SHALL include VALUE_NUM, UNIT, REF_LOW,
   REF_HIGH and MEASURED_AT. Rows SHALL be ordered by RULE_ID ascending and then by MEASURED_AT ascending.
6. THE Evidence_Join_Query SHALL return a Reference_Range_Flag with every returned LAB_RESULT. The flag is
   TRUE when VALUE_NUM is below a non-null REF_LOW or above a non-null REF_HIGH. It is FALSE otherwise,
   including when VALUE_NUM equals a bound or when a bound is null.
7. THE Evidence_Join_Query SHALL restrict the PATIENT_MEDICATION and LAB_RESULT rows it reads to those whose
   PATIENT_ID equals the patient id parameter.
8. WHEN the Evidence_Join_Query runs for the Demo_Patient with As_Of_Date 2026-11-13 and the DRUG_ID of
   ibuprofen as candidate, THE Evidence_Join_Query SHALL return exactly six rows:
   - three for the EGFR row of the Triple_Whammy_Rule, with VALUE_NUM 62, 55 and 48 and
     Reference_Range_Flags FALSE, TRUE and TRUE;
   - three for the CREATININE row of the Triple_Whammy_Rule, with VALUE_NUM 0.97, 1.07 and 1.20 and
     Reference_Range_Flags FALSE, FALSE and TRUE.

   Every row SHALL name exactly ramipril and furosemide as the supplying current medications and SHALL carry
   the ramipril `drug_interactions` section and the Evidence_Quote from Requirement 10 criterion 4.

9. WHEN the Evidence_Join_Query runs for the Demo_Patient with As_Of_Date 2026-11-13 and the CLASS_NAME
   'NSAID' as candidate, THE Evidence_Join_Query SHALL return the same six rows as in criterion 8, with
   identical values in every column.
10. WHEN the Evidence_Join_Query runs for the Demo_Patient with As_Of_Date 2026-11-13 and the DRUG_ID of
    ramipril as candidate, THE Evidence_Join_Query SHALL return exactly three rows, all for the
    Potassium_Rule. The rows SHALL have POTASSIUM VALUE_NUM 4.6, 4.9 and 5.1 with Reference_Range_Flags
    FALSE, FALSE and TRUE, no supplying current medication, and the ramipril `warnings_and_cautions` section
    with the Evidence_Quote from Requirement 10 criterion 5.
11. WHEN the Evidence_Join_Query runs for the Demo_Patient with As_Of_Date 2026-11-13 and the DRUG_ID of
    metoprolol succinate as candidate, THE Evidence_Join_Query SHALL return zero rows.
12. IF a matched Risk_Rule has no LAB_RESULT of the patient for its ANALYTE within the window of criterion 5,
    THEN THE Evidence_Join_Query SHALL return exactly one row for that Risk_Rule, with every LAB_RESULT
    column and the Reference_Range_Flag null. This keeps a missing lab result from being reported as an
    absent Risk_Rule match.
13. IF the call supplies both a candidate DRUG_ID and a candidate CLASS_NAME, or neither, THEN THE
    Join_Verification SHALL return Join_Status UNKNOWN_CANDIDATE naming the candidate parameters, without
    sending the Evidence_Join_Query to the Target_Database.
14. IF the candidate DRUG_ID has no DRUG_CLASS row, or the candidate CLASS_NAME equals no DRUG_CLASS
    CLASS_NAME, THEN THE Join_Verification SHALL return Join_Status UNKNOWN_CANDIDATE naming the candidate,
    and SHALL NOT return Join_Status NO_DOCUMENTED_INTERACTION_FOUND.

### Requirement 13: Join verification and result states

**User Story:** As the presenter, I want a single check that proves the join and the quote before the demo,
so that "no hit", "wrong patient" and "query failed" are never confused with each other.

#### Acceptance Criteria

1. WHEN the Evidence_Join_Query returns one or more rows, THE Join_Verification SHALL check each returned row
   with the Quote_Verifier, passing the returned Evidence_Quote as the quote and the returned SECTION_TEXT as
   the section text.
2. WHEN the Evidence_Join_Query returns one or more rows, THE Join_Verification SHALL recompute the
   Content_Hash of the returned SECTION_TEXT of each row and compare it with the returned CONTENT_SHA256 by
   exact string equality.
3. WHEN every returned row passes the quote check of criterion 1 and the hash check of criterion 2, THE
   Join_Verification SHALL return Join_Status EVIDENCE_FOUND with, for each matched Risk_Rule, the RULE_NAME,
   ANALYTE, DIRECTION, Evidence_Quote, SECTION_ID, LABEL_SET_ID, LABEL_EFFECTIVE_AT, the supplying current
   medications, and each returned LAB_RESULT with VALUE_NUM, UNIT, MEASURED_AT and its Reference_Range_Flag.
4. IF any returned row fails the quote check or the hash check, or has a null Evidence_Quote, SECTION_TEXT
   or CONTENT_SHA256, THEN THE Join_Verification SHALL return Join_Status EVIDENCE_UNVERIFIED instead of
   EVIDENCE_FOUND, even when other rows pass, and SHALL name the RULE_NAME, the SECTION_ID and the failed
   check (quote or hash) of every failing row.
5. WHEN the Evidence_Join_Query returns zero rows for a patient id that has a PATIENT row, THE
   Join_Verification SHALL return Join_Status NO_DOCUMENTED_INTERACTION_FOUND with the text
   "no documented interaction found", and its returned text SHALL contain none of the whole words "safe",
   "safely" or "safety".
6. IF no PATIENT row exists for the patient id, THEN THE Join_Verification SHALL return Join_Status
   UNKNOWN_PATIENT without running the Evidence_Join_Query.
7. IF the patient lookup or the Evidence_Join_Query raises a database error, THEN THE Join_Verification
   SHALL return Join_Status QUERY_FAILED with the database error message.
8. WHEN the Seed_Command has committed the rows of a seed run, THE Seed_Command SHALL run the
   Join_Verification for the Demo_Patient with As_Of_Date 2026-11-13 and candidate ibuprofen given as its
   DRUG_ID, and print the Join_Status with the details returned with it.
9. IF the Join_Verification run by the Seed_Command after a seed run or in Verify_Mode returns a Join_Status
   other than EVIDENCE_FOUND, THEN THE Seed_Command SHALL exit with a non-zero status without rolling back
   the committed seed rows.
10. WHEN the operator runs the Seed_Command in Verify_Mode, THE Seed_Command SHALL run the Join_Verification
    for the Demo_Patient with As_Of_Date 2026-11-13 and candidate ibuprofen given as its DRUG_ID, print the
    Join_Status with its details, and insert, update or delete no row and create, alter or drop no database
    object.
11. WHEN the Join_Verification run by the Seed_Command returns Join_Status EVIDENCE_FOUND, THE Seed_Command
    SHALL exit with status zero.
12. THE Join_Verification SHALL return exactly one Join_Status per invocation to its caller and leave the
    process exit status to the caller, so that the Integration_Check in Requirement 17 criterion 9 can assert
    each Join_Status.
13. WHEN a matched Risk_Rule's returned row has null LAB_RESULT columns (Requirement 12 criterion 12), THE
    Join_Verification SHALL include that Risk_Rule in its EVIDENCE_FOUND result with an empty lab list and
    the limitation text "no <ANALYTE> result in the 365 days up to <As_Of_Date>", with the ANALYTE code and
    the As_Of_Date filled in.
14. IF the candidate is invalid under Requirement 12 criterion 13 or 14, THEN THE Join_Verification SHALL
    return Join_Status UNKNOWN_CANDIDATE naming the candidate, without reporting
    NO_DOCUMENTED_INTERACTION_FOUND.

### Requirement 14: Trust rules for curated text

**User Story:** As the team, I want the seed data checked for wording that breaks MedGuard's trust rules, so
that the demo does not imply safety or give clinical advice.

#### Acceptance Criteria

1. IF any Curated_Text value in the Demo_Fixture contains the word "safe", "safely", "safer", "safest" or
   "safety" as a whole word, THEN THE Unit_Tests SHALL fail and report the Demo_Fixture field that holds the
   value and the matched word. A whole-word match ignores letter case and requires the word or phrase to be
   bounded at each end by the start or end of the value or by a character that is not a letter or digit.
   Under this rule "Safety" and "safe," match and "unsafe" does not.
2. IF any Curated_Text value in the Demo_Fixture, other than an UTTERANCE text, contains a phrase from the
   Banned_Phrase_List as a whole-word match as defined in criterion 1, THEN THE Unit_Tests SHALL fail and
   report the Demo_Fixture field that holds the value and the matched phrase.
3. WHEN the Join_Verification reports Join_Status NO_DOCUMENTED_INTERACTION_FOUND, THE Join_Verification
   SHALL print the exact text "no documented interaction found" as the wording for the absent Risk_Rule
   match, and its output SHALL contain none of the words listed in criterion 1.
4. THE Unit_Tests SHALL use a Banned_Phrase_List, committed with the tests, that assigns every phrase to
   exactly one of four categories: dose change, starting or stopping a medicine, diagnosis statement, and
   prescribing recommendation. Each category SHALL hold at least two phrases.
5. THE Unit_Tests SHALL assert that no Banned_Phrase_List entry is a whole-word match in any of the schedule
   texts "once a day", "twice a day", "three times a day", "in the morning" and "with breakfast".
6. THE Unit_Tests SHALL assert three things about the checks in criteria 1 and 2: they reject a sample text
   for each word listed in criterion 1, they reject a sample text for each banned-phrase category, and they
   accept the text "no documented interaction found".

### Requirement 15: Retire the legacy seed

**User Story:** As a team member, I want the old six-table seed removed, so that nobody re-creates the
legacy tables on top of the canonical schema.

#### Acceptance Criteria

1. THE Seed_Command source file `src/hackathon26/seed.py` SHALL contain no CREATE TABLE or ALTER TABLE
   statement and no code that builds rows for DRUG_PRODUCT, PRESCRIPTION, DISPENSING or REVIEW_QUEUE. It
   SHALL reference those four table names only in the Schema_Apply steps of Requirement 2 criteria 3 and 4.
2. WHEN Schema_Apply runs, THE Seed_Command SHALL create Canonical_Tables only by executing the statements
   of the Schema_File.
3. WHEN the Seed_Command runs without the Schema_Apply option, including in Verify_Mode, THE Seed_Command
   SHALL execute no CREATE, ALTER or DROP statement against the Target_Database.
4. IF the operator passes the legacy `--reset` option, with or without other options, THEN THE Seed_Command
   SHALL exit with a non-zero status before opening a connection to the Target_Database. It SHALL also print
   a message saying that `--reset` is retired and giving the name of the Schema_Apply option.
5. THE Seed_Command module docstring SHALL do four things. It SHALL give the exact command line for the
   Default_Seed_Run, Schema_Apply, Verify_Mode and the Label_Fetcher. It SHALL state that Schema_Apply drops
   the Legacy_Tables and recreates every Canonical_Table empty, including the App_Written_Tables. It SHALL
   state that Verify_Mode writes no rows. It SHALL state that the Label_Fetcher is the only one of these
   commands that contacts openFDA. The docstring SHALL mention `--reset` only as a retired option.
6. WHEN the Unit_Tests pass and a seed run against the Target_Database ends with Join_Status EVIDENCE_FOUND,
   THE PROJECT.md status list SHALL make three changes. It SHALL mark the "Seed data" item and the "FDA label
   ingestion" item as done. It SHALL change the table count of the schema item from 16 to 17, which is the
   16 original tables plus RISK_RULE_CLASS. It SHALL leave every other status item, and every other
   paragraph of the Status section (including the teammate-written listener/resolution note), unchanged.

### Requirement 16: Credentials and database scope

**User Story:** As the team, I want the data layer to keep credentials out of code and output and to touch
only the MEDGUARD schema, so that the shared event infrastructure stays safe to use.

#### Acceptance Criteria

1. THE Seed_Command, the Join_Verification and the Integration_Check SHALL obtain Exasol connection settings
   and credentials only by calling `connect()` in `src/hackathon26/db.py`, without reading a password from
   any other source and without opening a database connection by any other means.
2. THE Seed_Command and the Label_Fetcher SHALL exclude every credential value from their standard output
   and standard error, in runs that succeed and in runs that exit with a non-zero status, where a credential
   value is the Exasol password, any API key, or any AWS secret access key or session token.
3. THE Seed_Command SHALL, in the Default_Seed_Run, Schema_Apply and Verify_Mode, create, alter or drop only
   the MEDGUARD_Schema and objects inside it, and insert, update or delete rows only in tables inside the
   MEDGUARD_Schema, including when the `EXASOL_SCHEMA` setting read by `connect()` is unset or names a
   different schema.
4. THE Demo_Fixture, Label_Manifest, Label_Snapshots and Snapshot_Metadata SHALL contain no credential value
   as defined in criterion 2 and no patient record other than the synthetic Demo_Patient.
5. THE Seed_Command and the Join_Verification SHALL read only from tables in the MEDGUARD_Schema and from
   Exasol system tables.
6. IF `connect()` raises an error, THEN THE Seed_Command SHALL exit with a non-zero status without writing
   any row and print the connection error message without any credential value.

### Requirement 17: Tests

**User Story:** As a developer, I want fast offline tests plus one opt-in database check, so that the data
layer can be trusted before the demo without touching the network on every test run.

#### Acceptance Criteria

1. WHEN `uv run pytest tests/unit` runs on a machine with no network connection, no reachable
   Target_Database and no Exasol credentials configured, THE Unit_Tests SHALL exit with status 0, report no
   test as skipped, and finish in under 60 seconds of wall-clock time.
2. THE Unit_Tests SHALL test Requirement 11 criteria 2 and 3 as property-based tests. Each test SHALL run at
   least 100 generated cases over text that includes non-ASCII characters. The Unit_Tests SHALL also test
   Requirement 11 criteria 4 and 5 with example cases: an empty quote, and quotes that differ from a
   substring of the section text only in whitespace, only in letter case, or only in straight versus
   typographic quotation marks. The property-based testing library SHALL be declared in the `dev`
   dependency group of `pyproject.toml`.
3. THE Unit_Tests SHALL test the Label_Importer against a committed openFDA-shaped fixture label of at most
   20 KB with a matching Snapshot_Metadata record. The fixture SHALL contain at least two
   Imported_Section_Fields, one Imported_Section_Field with two or more string elements, one empty-string
   element, one field that is not an Imported_Section_Field, and section text with leading and trailing
   whitespace, line breaks and non-ASCII characters. The Unit_Tests SHALL assert the behaviour in
   Requirement 8 criteria 3 to 6 and 8. This includes that the non-imported field yields no row, and that
   CONTENT_SHA256 equals a SHA-256 the test computes independently of the Label_Importer.
4. THE Unit_Tests SHALL test, reading the same Demo_Fixture that the Seed_Command loads rather than a copy,
   the Demo_Fixture invariants in Requirement 1 criterion 10, Requirement 4 criteria 6, 7, 9 and 10,
   Requirement 5 criteria 4 to 6 and 8, Requirement 6 criteria 2 to 11, and Requirement 9 criteria 8, 9
   and 12.
5. THE Unit_Tests SHALL build the rows of every Seed_Owned_Table twice from the same Demo_Fixture and
   Label_Snapshots without a Target_Database connection. The tests SHALL assert that both builds yield the
   same rows, equal in every column and with the same primary key values, and that every date and timestamp
   value in the built rows occurs in the Demo_Fixture or the Snapshot_Metadata.
6. THE Unit_Tests SHALL test the Snapshot_Metadata round trip in Requirement 7 criterion 10 in two ways: as
   a property-based test of at least 100 generated records, each with a request URL, a UTC fetch timestamp
   and a 64-character lowercase hexadecimal SHA-256, and by round-tripping every committed
   Snapshot_Metadata record.
7. THE Unit_Tests SHALL import every committed Label_Snapshot with the Label_Importer and assert
   Requirement 8 criterion 9 for every resulting row. For every Evidence_Quote in the Demo_Fixture, the
   Unit_Tests SHALL check with the Quote_Verifier that the quote is a substring of the SECTION_TEXT of the
   section row its Risk_Rule links to; a failing check SHALL name the RULE_NAME, LABEL_SET_ID and
   SECTION_TYPE. If a Label_Snapshot listed in the Label_Manifest is missing, the test SHALL fail, not skip,
   and name the drug.
8. WHERE `MEDGUARD_INTEGRATION` is set to `1`, THE Integration_Check SHALL run the Default_Seed_Run of the
   Seed_Command twice in succession against the Target_Database and assert that:
   - both runs exit with status 0;
   - every Canonical_Table holds the same row count after the second run as after the first;
   - every Seed_Owned_Table holds the same rows, equal in every column, after the second run as after the
     first;
   - every App_Written_Table holds the same rows after the second run as before the first.
9. WHERE `MEDGUARD_INTEGRATION` is set to `1`, THE Integration_Check SHALL run the Join_Verification with
   As_Of_Date 2026-11-13 and assert these results:
   - For the Demo_Patient with candidate ibuprofen, and again with candidate class 'NSAID': Join_Status
     EVIDENCE_FOUND, with the two Triple_Whammy_Rule rows as the only matched Risk_Rules and with the
     supplying medications and lab values in Requirement 12 criterion 8.
   - For the Demo_Patient with candidate ramipril: Join_Status EVIDENCE_FOUND, with the Potassium_Rule as the
     only matched Risk_Rule and the POTASSIUM values in Requirement 12 criterion 10.
   - In every returned lab value of these EVIDENCE_FOUND results, the Reference_Range_Flag is TRUE exactly
     for EGFR 55 and 48, CREATININE 1.20 and POTASSIUM 5.1.
   - For the Demo_Patient with candidate metoprolol succinate: Join_Status NO_DOCUMENTED_INTERACTION_FOUND
     with the text "no documented interaction found".
   - For a patient id that has no PATIENT row, with candidate ibuprofen: Join_Status UNKNOWN_PATIENT.
   - For the Demo_Patient with candidate class 'nsaid' (wrong case): Join_Status UNKNOWN_CANDIDATE.
10. WHILE `MEDGUARD_INTEGRATION` is unset or set to any value other than `1`, THE Integration_Check SHALL be
    reported by pytest as skipped, without opening a connection to the Target_Database and without
    resolving Exasol credentials.
11. THE Integration_Check SHALL change the Target_Database only by running the Default_Seed_Run of the
    Seed_Command. It SHALL call the Join_Verification read-only, SHALL NOT run Schema_Apply, and SHALL NOT
    write rows by any other means.
12. THE Unit_Tests SHALL test the Join_Verification without a Target_Database, using supplied
    Evidence_Join_Query results, and assert these statuses:
    - EVIDENCE_UNVERIFIED, naming the RULE_NAME and SECTION_ID, when a returned Evidence_Quote is not a
      substring of the returned SECTION_TEXT;
    - EVIDENCE_UNVERIFIED when a returned CONTENT_SHA256 differs from the Content_Hash of the returned
      SECTION_TEXT;
    - QUERY_FAILED, with the error message, when the query raises a database error;
    - NO_DOCUMENTED_INTERACTION_FOUND, with the text "no documented interaction found", when the query
      returns zero Risk_Rule rows for an existing patient;
    - UNKNOWN_CANDIDATE when the call supplies both or neither of a candidate DRUG_ID and CLASS_NAME;
    - EVIDENCE_FOUND with an empty lab list and the limitation from Requirement 13 criterion 13 when a
      matched Risk_Rule row has null LAB_RESULT columns.
13. IF `MEDGUARD_INTEGRATION` is set to `1` and the Target_Database cannot be reached, no Exasol credentials
    resolve, or a Canonical_Table is missing or has mismatched columns, THEN THE Integration_Check SHALL be
    reported by pytest as failed, not skipped. The failure message SHALL state which of these causes
    occurred and SHALL contain no credential value.
14. THE Unit_Tests SHALL test that the label checks of the Seed_Command report an error naming the drug,
    without opening a database connection, in three cases:
    - a fixture label that lacks `set_id` (Requirement 8 criterion 7);
    - a fixture label whose `effective_time` is not a valid YYYYMMDD date (Requirement 8 criterion 7);
    - a Label_Snapshot whose SHA-256 differs from its Snapshot_Metadata (Requirement 8 criterion 2).
