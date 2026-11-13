-- MedGuard schema — Healthcare Hackathon Bayern 2026
--
-- Design principle: every claim the app makes must be traceable to a row here.
-- Nothing is asserted that cannot be joined back to a source.
--
-- SYNTHETIC DATA ONLY. No real patient data (also required by the AWS event terms).

CREATE SCHEMA IF NOT EXISTS MEDGUARD;
OPEN SCHEMA MEDGUARD;

-- ---------------------------------------------------------------------------
-- Reference drug knowledge (public sources: RxNorm / RxClass / openFDA)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE TABLE DRUG (
    DRUG_ID            DECIMAL(10,0),
    RXCUI              VARCHAR(20),          -- RxNorm concept id, null if unmapped
    GENERIC_NAME       VARCHAR(200) NOT NULL,
    BRAND_NAMES        VARCHAR(500),
    IS_OTC             BOOLEAN DEFAULT FALSE, -- OTC drugs are the ones patients forget to mention
    SRC_NAME           VARCHAR(100),
    SOURCE_FETCHED_AT  TIMESTAMP,
    PRIMARY KEY (DRUG_ID)
);

-- A drug belongs to several classes. Interaction warnings are usually written
-- about a CLASS ("ACE inhibitors"), not a drug name — this is why name search alone misses them.
CREATE OR REPLACE TABLE DRUG_CLASS (
    DRUG_ID      DECIMAL(10,0) NOT NULL,
    CLASS_NAME   VARCHAR(200)  NOT NULL,     -- e.g. 'ACE inhibitor'
    CLASS_TYPE   VARCHAR(50),                -- EPC | MOA | CYP | ATC
    SRC_NAME     VARCHAR(100)
);

-- Synonyms bridge the gap between how inserts phrase a class and how RxClass names it.
-- e.g. insert says 'potassium-sparing diuretics', RxClass says 'Aldosterone Antagonist'.
CREATE OR REPLACE TABLE CLASS_SYNONYM (
    CLASS_NAME   VARCHAR(200) NOT NULL,
    SYNONYM      VARCHAR(200) NOT NULL,
    CURATED_BY   VARCHAR(100)
);

-- Official package-insert text, split by section. This is the evidence store:
-- every interaction finding must quote a row from here.
CREATE OR REPLACE TABLE DRUG_LABEL_SECTION (
    SECTION_ID         DECIMAL(10,0),
    DRUG_ID            DECIMAL(10,0) NOT NULL,
    SECTION_TYPE       VARCHAR(50)  NOT NULL, -- boxed_warning | contraindications | warnings | drug_interactions
    SECTION_TEXT       VARCHAR(2000000),
    LABEL_SET_ID       VARCHAR(100),          -- openFDA set id, so a quote can be traced to one document
    LABEL_EFFECTIVE_AT DATE,
    SOURCE_URL         VARCHAR(500),
    SOURCE_FETCHED_AT  TIMESTAMP,
    PRIMARY KEY (SECTION_ID)
);

-- Physical appearance — how a patient actually describes a pill ("the small yellow one").
CREATE OR REPLACE TABLE DRUG_APPEARANCE (
    DRUG_ID      DECIMAL(10,0) NOT NULL,
    COLOR        VARCHAR(50),
    SHAPE        VARCHAR(50),
    IMPRINT      VARCHAR(100),
    STRENGTH     VARCHAR(50),
    MANUFACTURER VARCHAR(200),
    SRC_NAME     VARCHAR(100)
);

-- ---------------------------------------------------------------------------
-- Patient data (synthetic)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE TABLE PATIENT (
    PATIENT_ID   DECIMAL(10,0),
    DISPLAY_NAME VARCHAR(100) NOT NULL,       -- synthetic, e.g. 'Patient A (72F)'
    BIRTH_YEAR   DECIMAL(4,0),
    SEX          VARCHAR(10),
    PRIMARY_DX   VARCHAR(200),
    IS_SYNTHETIC BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (PATIENT_ID)
);

CREATE OR REPLACE TABLE PATIENT_MEDICATION (
    PATIENT_MED_ID DECIMAL(10,0),
    PATIENT_ID     DECIMAL(10,0) NOT NULL,
    DRUG_ID        DECIMAL(10,0) NOT NULL,
    STRENGTH       VARCHAR(50),
    SCHEDULE_TEXT  VARCHAR(200),              -- 'once in the morning'
    STARTED_ON     DATE,
    STOPPED_ON     DATE,                      -- null = currently taking
    PRIMARY KEY (PATIENT_MED_ID)
);

-- Lab results are what make advice patient-specific. The same drug pair is safe in
-- one patient and dangerous in another, and this table is the difference.
CREATE OR REPLACE TABLE LAB_RESULT (
    LAB_ID        DECIMAL(10,0),
    PATIENT_ID    DECIMAL(10,0) NOT NULL,
    ANALYTE       VARCHAR(50) NOT NULL,       -- POTASSIUM | CREATININE | EGFR | SODIUM | NT_PROBNP
    VALUE_NUM     DECIMAL(10,3),
    UNIT          VARCHAR(20),
    REF_LOW       DECIMAL(10,3),
    REF_HIGH      DECIMAL(10,3),
    MEASURED_AT   DATE NOT NULL,
    PRIMARY KEY (LAB_ID)
);

-- Rules linking a drug/class combination to a lab analyte that modulates the risk.
-- e.g. an ACE inhibitor + a potassium-sparing diuretic is governed by POTASSIUM.
CREATE OR REPLACE TABLE RISK_LAB_RULE (
    RULE_ID        DECIMAL(10,0),
    RULE_NAME      VARCHAR(200) NOT NULL,
    ANALYTE        VARCHAR(50)  NOT NULL,
    DIRECTION      VARCHAR(10),               -- HIGH = risk when value rises
    CONCERN_AT     DECIMAL(10,3),             -- threshold where this becomes notable
    RATIONALE      VARCHAR(1000),
    SRC_NAME       VARCHAR(500),
    PRIMARY KEY (RULE_ID)
);

-- ---------------------------------------------------------------------------
-- Consultation (the scripted conversation driving the demo)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE TABLE CONSULTATION (
    CONSULT_ID   DECIMAL(10,0),
    PATIENT_ID   DECIMAL(10,0) NOT NULL,
    CLINICIAN    VARCHAR(100),
    STARTED_AT   TIMESTAMP,
    SCENARIO     VARCHAR(200),
    PRIMARY KEY (CONSULT_ID)
);

CREATE OR REPLACE TABLE UTTERANCE (
    UTTERANCE_ID DECIMAL(10,0),
    CONSULT_ID   DECIMAL(10,0) NOT NULL,
    SEQ          DECIMAL(6,0)  NOT NULL,      -- replay order
    SPEAKER      VARCHAR(20)   NOT NULL,      -- DOCTOR | PATIENT
    UTTERANCE_TEXT VARCHAR(4000) NOT NULL,
    OFFSET_MS    DECIMAL(10,0),               -- for timed replay
    PRIMARY KEY (UTTERANCE_ID)
);

-- What the app heard and what it decided a mention referred to.
-- Deliberately records the AMBIGUITY, not just the winner.
CREATE OR REPLACE TABLE DRUG_MENTION (
    MENTION_ID     DECIMAL(10,0),
    UTTERANCE_ID   DECIMAL(10,0) NOT NULL,
    RAW_TEXT       VARCHAR(500) NOT NULL,     -- 'the small yellow one'
    MENTION_TYPE   VARCHAR(30),               -- NAME | APPEARANCE | INDICATION | CLASS
    RESOLVED_DRUG_ID DECIMAL(10,0),           -- null when unresolved
    CONFIDENCE     DECIMAL(4,3),              -- 0..1
    RESOLUTION_BASIS VARCHAR(500),            -- why: 'colour+shape match on patient med list'
    NEEDS_REVIEW   BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (MENTION_ID)
);

-- Competing candidates for an ambiguous mention. Showing these is a trust feature:
-- the doctor sees what the system considered, not just what it picked.
CREATE OR REPLACE TABLE MENTION_CANDIDATE (
    MENTION_ID   DECIMAL(10,0) NOT NULL,
    DRUG_ID      DECIMAL(10,0) NOT NULL,
    SCORE        DECIMAL(4,3),
    BASIS        VARCHAR(500)
);

-- ---------------------------------------------------------------------------
-- Findings and oversight
-- ---------------------------------------------------------------------------

-- One row per risk surfaced to the clinician. EVIDENCE_QUOTE must be verbatim from
-- DRUG_LABEL_SECTION; the loader verifies this rather than trusting the model.
CREATE OR REPLACE TABLE FINDING (
    FINDING_ID        DECIMAL(10,0),
    CONSULT_ID        DECIMAL(10,0) NOT NULL,
    TRIGGER_DRUG_ID   DECIMAL(10,0),          -- the drug being considered/added
    AGAINST_DRUG_ID   DECIMAL(10,0),          -- the existing drug it conflicts with
    SEVERITY          VARCHAR(10),            -- RED | AMBER | GREY
    HEADLINE          VARCHAR(500),
    EVIDENCE_QUOTE    VARCHAR(4000),          -- verbatim from the insert
    EVIDENCE_SECTION_ID DECIMAL(10,0),        -- which section it came from
    MATCH_BASIS       VARCHAR(30),            -- NAME | CLASS | ENZYME (name = higher confidence)
    CONFIDENCE        DECIMAL(4,3),
    LAB_CONTEXT       VARCHAR(1000),          -- 'eGFR 48 and falling (was 62 in May)'
    LAB_RULE_ID       DECIMAL(10,0),
    UNVERIFIED_NOTE   VARCHAR(1000),          -- what the system could NOT check
    CREATED_AT        TIMESTAMP,
    PRIMARY KEY (FINDING_ID)
);

-- Human oversight. Every finding ends with a clinician decision, and it is recorded.
CREATE OR REPLACE TABLE CLINICIAN_REVIEW (
    REVIEW_ID    DECIMAL(10,0),
    FINDING_ID   DECIMAL(10,0) NOT NULL,
    DECISION     VARCHAR(20),                 -- ACCEPTED | OVERRIDDEN | DEFERRED
    REVIEWER     VARCHAR(100),
    NOTE         VARCHAR(1000),
    DECIDED_AT   TIMESTAMP,
    PRIMARY KEY (REVIEW_ID)
);

-- Full audit trail, including every model call, so the demo can show provenance.
CREATE OR REPLACE TABLE AUDIT_LOG (
    AUDIT_ID     DECIMAL(10,0),
    CONSULT_ID   DECIMAL(10,0),
    EVENT_TYPE   VARCHAR(50),                 -- MENTION_RESOLVED | FINDING_RAISED | MODEL_CALL | REVIEW
    DETAIL       VARCHAR(4000),
    MODEL_ID     VARCHAR(100),
    CREATED_AT   TIMESTAMP,
    PRIMARY KEY (AUDIT_ID)
);
