"""Create the MEDGUARD schema and load SYNTHETIC demo data into Exasol.

Everything here is invented: patients, prescriptions, manufacturers and especially pill appearances
(colour, shape, imprint). None of it describes a real product or person. Do not use it clinically.

Usage (from the repo root):
    uv run python src/hackathon26/seed.py            # create schema + tables + data; stops if tables exist
    uv run python src/hackathon26/seed.py --reset    # drop and recreate only the tables this script owns
"""
from __future__ import annotations

import argparse
import random
from datetime import date

try:
    from hackathon26.db import connect
except ImportError:  # running as a plain script: src/hackathon26 is on sys.path
    from db import connect

SCHEMA = "MEDGUARD"
SEED = 26
TODAY = date(2026, 11, 13)  # fixed so the data is reproducible
MONTHS_OF_HISTORY = 6
N_PATIENTS = 24

# (active ingredient, strengths in mg, plain-language purpose)
INGREDIENTS = [
    ("Metoprolol succinate", [
     47.5, 95], "Heart: slows the heartbeat and eases the heart's workload"),
    ("Bisoprolol", [2.5, 5],
     "Heart: slows the heartbeat and eases the heart's workload"),
    ("Carvedilol", [6.25, 12.5],
     "Heart: slows the heartbeat and lowers blood pressure"),
    ("Ramipril", [2.5, 5], "Heart and blood pressure: relaxes blood vessels"),
    ("Enalapril", [10], "Heart and blood pressure: relaxes blood vessels"),
    ("Candesartan", [8], "Heart and blood pressure: relaxes blood vessels"),
    ("Spironolactone", [25],
     "Water tablet: helps the body get rid of extra fluid"),
    ("Furosemide", [40],
     "Water tablet: helps the body get rid of extra fluid"),
    ("Torasemide", [10],
     "Water tablet: helps the body get rid of extra fluid"),
    ("Dapagliflozin", [10],
     "Heart and kidneys: protects the heart in heart failure"),
    ("Empagliflozin", [10],
     "Heart and kidneys: protects the heart in heart failure"),
    ("Apixaban", [5], "Blood thinner: lowers the risk of blood clots"),
    ("Atorvastatin", [20], "Cholesterol: lowers blood fats"),
    ("Pantoprazole", [20], "Stomach: protects the stomach lining"),
    ("Levothyroxine", [50], "Thyroid: replaces thyroid hormone"),
    ("Metformin", [500], "Blood sugar: helps control diabetes"),
    ("Amlodipine", [5], "Blood pressure: relaxes blood vessels"),
]

# Fictional companies. The first one plays the originator, the others make generics.
MANUFACTURERS = ["Nordpharm", "Alpenmed", "Isarpharma",
                 "Franconia Generics", "Mainwerk Pharma"]
COLOURS = ["white", "white", "white", "yellow",
           "yellow", "pink", "blue", "orange", "green", "brown"]
SHAPES = ["round", "round", "oval", "oblong", "capsule-shaped", "heart-shaped"]
SCHEDULES = [
    ("once a day, morning", 1),
    ("once a day, evening", 1),
    ("twice a day, morning and evening", 2),
]


def build_products(rng: random.Random) -> list[tuple]:
    """DRUG_PRODUCT rows: one originator and two generics per ingredient and strength."""
    rows, product_id, seen = [], 1000, set()
    for ingredient, strengths, purpose in INGREDIENTS:
        for strength in strengths:
            for i, maker in enumerate(rng.sample(MANUFACTURERS, 3)):
                while True:  # keep (ingredient, strength, colour, shape) distinct per product
                    colour, shape = rng.choice(COLOURS), rng.choice(SHAPES)
                    if (ingredient, strength, colour, shape) not in seen:
                        seen.add((ingredient, strength, colour, shape))
                        break
                imprint = f"{maker[:2].upper()} {rng.randint(10, 99)}{rng.choice('ABCDEFGH')}"
                is_generic = i > 0
                name = f"{ingredient.split()[0]} {maker}" if is_generic else f"{ingredient.split()[0][:4]}vera"
                rows.append((
                    product_id, ingredient, f"{name} {strength:g} mg", strength, "tablet",
                    colour, shape, imprint, maker, is_generic, purpose,
                ))
                product_id += 1
    return rows


def build_patients(rng: random.Random) -> list[tuple]:
    return [
        (f"P{n:03d}", f"Demo Patient {n:02d}", rng.randint(
            1938, 1960), rng.choice(["de", "de", "en"]))
        for n in range(1, N_PATIENTS + 1)
    ]


def months_back(n: int) -> date:
    """First day of the month, n months before TODAY."""
    total = TODAY.year * 12 + (TODAY.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


def build_prescriptions_and_dispensing(rng, patients, products):
    by_ingredient: dict[tuple, list[tuple]] = {}
    for p in products:
        by_ingredient.setdefault((p[1], float(p[3])), []).append(p)
    options = list(by_ingredient)

    rx_rows, dispense_rows = [], []
    rx_id, dispense_id = 5000, 90000
    for patient in patients:
        # Heart-failure core plus a few comorbidity drugs.
        chosen = rng.sample(options, rng.randint(5, 8))
        for ingredient, strength in chosen:
            schedule, times = rng.choice(SCHEDULES)
            started = months_back(rng.randint(MONTHS_OF_HISTORY, 36))
            rx_rows.append(
                (rx_id, patient[0], ingredient, strength, schedule, times, started.isoformat()))

            current = rng.choice(by_ingredient[(ingredient, strength)])
            # About a third of prescriptions get a generic switch somewhere in the history.
            switch_at = rng.randint(
                1, MONTHS_OF_HISTORY) if rng.random() < 0.35 else None
            for m in range(MONTHS_OF_HISTORY, -1, -1):
                if switch_at is not None and m == MONTHS_OF_HISTORY - switch_at:
                    current = rng.choice(
                        [x for x in by_ingredient[(ingredient, strength)] if x[0] != current[0]])
                dispense_rows.append(
                    (dispense_id, rx_id, current[0], months_back(m).isoformat()))
                dispense_id += 1
            rx_id += 1
    return rx_rows, dispense_rows


DDL = {
    "DRUG_PRODUCT": """
        CREATE TABLE DRUG_PRODUCT (
            PRODUCT_ID DECIMAL(9,0) PRIMARY KEY,
            ACTIVE_INGREDIENT VARCHAR(100) NOT NULL,
            PRODUCT_NAME VARCHAR(100) NOT NULL,
            STRENGTH_MG DECIMAL(9,2) NOT NULL,
            FORM VARCHAR(30) NOT NULL,
            COLOUR VARCHAR(30) NOT NULL,
            SHAPE VARCHAR(30) NOT NULL,
            IMPRINT VARCHAR(30),
            MANUFACTURER VARCHAR(100) NOT NULL,
            IS_GENERIC BOOLEAN NOT NULL,
            PURPOSE_PLAIN VARCHAR(200)
        )""",
    "PATIENT": """
        CREATE TABLE PATIENT (
            PATIENT_ID VARCHAR(10) PRIMARY KEY,
            DISPLAY_NAME VARCHAR(100) NOT NULL,
            BIRTH_YEAR DECIMAL(4,0),
            LANGUAGE VARCHAR(5)
        )""",
    "PRESCRIPTION": """
        CREATE TABLE PRESCRIPTION (
            RX_ID DECIMAL(9,0) PRIMARY KEY,
            PATIENT_ID VARCHAR(10) NOT NULL,
            ACTIVE_INGREDIENT VARCHAR(100) NOT NULL,
            STRENGTH_MG DECIMAL(9,2) NOT NULL,
            SCHEDULE_TEXT VARCHAR(100) NOT NULL,
            TIMES_PER_DAY DECIMAL(2,0) NOT NULL,
            START_DATE DATE NOT NULL
        )""",
    "DISPENSING": """
        CREATE TABLE DISPENSING (
            DISPENSE_ID DECIMAL(9,0) PRIMARY KEY,
            RX_ID DECIMAL(9,0) NOT NULL,
            PRODUCT_ID DECIMAL(9,0) NOT NULL,
            DISPENSED_ON DATE NOT NULL
        )""",
    # Written by the app, so created empty.
    "REVIEW_QUEUE": """
        CREATE TABLE REVIEW_QUEUE (
            REVIEW_ID DECIMAL(18,0) IDENTITY PRIMARY KEY,
            PATIENT_ID VARCHAR(10) NOT NULL,
            PATIENT_WORDS VARCHAR(2000),
            TOP_PRODUCT_ID DECIMAL(9,0),
            CONFIDENCE DECIMAL(4,3),
            STATUS VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
            CREATED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            REVIEWED_BY VARCHAR(100),
            REVIEWED_AT TIMESTAMP,
            CLINICIAN_NOTE VARCHAR(2000)
        )""",
    "AUDIT_LOG": """
        CREATE TABLE AUDIT_LOG (
            EVENT_ID DECIMAL(18,0) IDENTITY PRIMARY KEY,
            EVENT_TS TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            ACTOR VARCHAR(100) NOT NULL,
            EVENT_ACTION VARCHAR(100) NOT NULL,
            PATIENT_ID VARCHAR(10),
            DETAIL VARCHAR(2000)
        )""",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true",
                        help="drop and recreate the tables this script owns")
    args = parser.parse_args()

    rng = random.Random(SEED)
    products = build_products(rng)
    patients = build_patients(rng)
    rx_rows, dispense_rows = build_prescriptions_and_dispensing(
        rng, patients, products)

    with connect() as c:
        c.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        c.execute(f"OPEN SCHEMA {SCHEMA}")
        existing = {
            r[0]
            for r in c.execute(
                "SELECT TABLE_NAME FROM SYS.EXA_ALL_TABLES WHERE TABLE_SCHEMA = {s}", {
                    "s": SCHEMA}
            ).fetchall()
        }
        clash = existing & set(DDL)
        if clash and not args.reset:
            raise SystemExit(
                f"Tables already exist in {SCHEMA}: {sorted(clash)}. Use --reset to recreate them.")
        for name in DDL:
            if name in existing:
                c.execute(f"DROP TABLE {SCHEMA}.{name}")
        for ddl in DDL.values():
            c.execute(ddl)

        c.ext.insert_multi((SCHEMA, "DRUG_PRODUCT"), products)
        c.ext.insert_multi((SCHEMA, "PATIENT"), patients)
        c.ext.insert_multi((SCHEMA, "PRESCRIPTION"), rx_rows)
        c.ext.insert_multi((SCHEMA, "DISPENSING"), dispense_rows)
        c.commit()

        for name in DDL:
            n = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{name}").fetchval()
            print(f"{SCHEMA}.{name}: {n} rows")


if __name__ == "__main__":
    main()
