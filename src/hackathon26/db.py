"""Exasol connection helper.

Reads connection settings from the environment (see `.env.example`), falling back to the
local Exasol Personal deployment's generated secrets so a fresh checkout works with no setup
beyond `exasol install local`.
"""

from __future__ import annotations

import json
import os
import ssl
from functools import lru_cache
from pathlib import Path

import pyexasol

DEPLOYMENT_DIR = Path.home() / ".exasol" / "personal" / "deployments" / "default"
SECRETS_FILE = DEPLOYMENT_DIR / "secrets.json"
DEPLOYMENT_FILE = DEPLOYMENT_DIR / "deployment.json"


@lru_cache(maxsize=1)
def _deployment() -> dict:
    """Connection block written by the Exasol launcher, or {} if not deployed locally."""
    try:
        return json.loads(DEPLOYMENT_FILE.read_text()).get("connection", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _local_password() -> str | None:
    """The per-deployment password the launcher generates. Never commit this."""
    try:
        return json.loads(SECRETS_FILE.read_text())["dbPassword"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def settings() -> dict:
    """Resolved connection settings. Environment wins; local deployment fills the gaps."""
    dep = _deployment()
    host = os.getenv("EXASOL_HOST") or dep.get("host") or "127.0.0.1"
    port = os.getenv("EXASOL_PORT") or dep.get("dbPort") or 8563
    password = os.getenv("EXASOL_PASSWORD") or _local_password()
    if not password:
        raise RuntimeError(
            "No Exasol password. Set EXASOL_PASSWORD in .env, or run `exasol install local` "
            f"so the launcher writes {SECRETS_FILE}."
        )
    return {
        "dsn": f"{host}:{port}",
        "user": os.getenv("EXASOL_USER") or dep.get("username") or "sys",
        "password": password,
        "schema": os.getenv("EXASOL_SCHEMA", ""),
    }


def connect(**overrides) -> pyexasol.ExaConnection:
    """Open a connection to Exasol.

    The local deployment uses a self-signed certificate, so validation is disabled. That is
    fine for 127.0.0.1; do not copy this setting for a remote database.
    """
    cfg = settings() | overrides
    schema = cfg.pop("schema", "")
    conn = pyexasol.connect(
        **cfg,
        websocket_sslopt={"cert_reqs": ssl.CERT_NONE},
        compression=True,
    )
    if schema:
        conn.execute(f"OPEN SCHEMA {schema}")
    return conn


if __name__ == "__main__":  # quick connectivity check
    with connect() as c:
        version = c.execute(
            "SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'"
        ).fetchval()
        print(f"Connected to Exasol {version} at {settings()['dsn']}")
