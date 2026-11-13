"""Check every prerequisite the demo needs, in one command. Read-only apart from one small model call.

    uv run python scripts/preflight.py

Exit code 0 means all checks passed. Never prints credentials.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hackathon26 import bedrock, db  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrap(fn):
        try:
            detail = fn()
            results.append((name, True, detail))
        except Exception as e:  # report every failure, keep going
            results.append((name, False, f"{type(e).__name__}: {e}"[:300]))
        return fn
    return wrap


@check("Exasol connection")
def _exasol():
    with db.connect() as c:
        version = c.execute(
            "SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'"
        ).fetchval()
    return f"Exasol {version} at {db.settings()['host']}"


@check("Exasol MEDGUARD schema matches sql/01_schema.sql")
def _schema():
    expected = set(re.findall(r"CREATE OR REPLACE TABLE (\w+)", (ROOT / "sql/01_schema.sql").read_text()))
    with db.connect() as c:
        live = {r[0] for r in c.execute(
            "SELECT TABLE_NAME FROM SYS.EXA_ALL_TABLES WHERE TABLE_SCHEMA = 'MEDGUARD'").fetchall()}
    missing, extra = sorted(expected - live), sorted(live - expected)
    if missing:
        raise RuntimeError(f"missing {len(missing)}/{len(expected)}: {missing}; not in schema file: {extra}")
    return f"{len(expected)} tables present"


@check("AWS sandbox account")
def _account():
    expected = os.getenv("SANDBOX_AWS_ACCOUNT_ID", "").strip()
    sess = bedrock.session()
    actual = sess.client("sts").get_caller_identity()["Account"]
    if not expected:
        raise RuntimeError("SANDBOX_AWS_ACCOUNT_ID is not set in .env")
    if actual != expected:
        raise RuntimeError(f"caller is {actual}, expected {expected}")
    return f"{actual} in {sess.region_name}"


@check("Bedrock model call")
def _model():
    reply = bedrock.ask("Reply with exactly: OK", max_tokens=50)
    if "OK" not in reply:
        raise RuntimeError(f"unexpected reply {reply!r}")
    return bedrock.DEFAULT_MODEL


@check("Bedrock Guardrail")
def _guardrail():
    gid = os.getenv("BEDROCK_GUARDRAIL_ID", "").strip()
    version = os.getenv("BEDROCK_GUARDRAIL_VERSION", "").strip()
    if not (gid and version):
        raise RuntimeError("BEDROCK_GUARDRAIL_ID/VERSION not set; run scripts/create_guardrail.py")
    g = bedrock.session().client("bedrock").get_guardrail(guardrailIdentifier=gid, guardrailVersion=version)
    if g["status"] != "READY":
        raise RuntimeError(f"status {g['status']}")
    return f"{g['name']} v{version} READY"


@check("openFDA label API")
def _openfda():
    url = 'https://api.fda.gov/drug/label.json?search=openfda.generic_name:"ramipril"&limit=1'
    with urllib.request.urlopen(url.replace('"', "%22"), timeout=15) as r:
        label = json.load(r)["results"][0]
    return f"reachable; ramipril label set_id {label['set_id']}"


if __name__ == "__main__":
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
