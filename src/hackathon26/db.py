"""Exasol connection helper.

Reads connection settings from the environment (see `.env.example`), falling back to an Exasol
Personal deployment's generated files. The deployment directory is `EXASOL_DEPLOYMENT_DIR` if set
(for example an AWS deployment), otherwise the local default under `~/.exasol`.

TLS: for a remote host, set `EXASOL_CERT_FINGERPRINT` (shown in the deployment's
`connection-instructions.txt`) so the self-signed certificate is verified by pinning. Certificate
validation is only disabled for a local 127.0.0.1 deployment.
"""
from __future__ import annotations

import json
import os
import ssl
from functools import lru_cache
from pathlib import Path

import pyexasol
from dotenv import load_dotenv

load_dotenv()

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def deployment_dir() -> Path:
    override = os.getenv("EXASOL_DEPLOYMENT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".exasol" / "personal" / "deployments" / "default"


@lru_cache(maxsize=1)
def _deployment() -> dict:
    """Connection block written by the Exasol launcher, or {} if not found."""
    try:
        return json.loads((deployment_dir() / "deployment.json").read_text()).get("connection", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _deployment_password() -> str | None:
    """The per-deployment password the launcher generates. Never commit this."""
    try:
        return json.loads((deployment_dir() / "secrets.json").read_text())["dbPassword"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def settings() -> dict:
    """Resolved connection settings. Environment wins; the deployment files fill the gaps."""
    dep = _deployment()
    host = os.getenv("EXASOL_HOST") or dep.get("host") or "127.0.0.1"
    port = os.getenv("EXASOL_PORT") or dep.get("dbPort") or 8563
    password = os.getenv("EXASOL_PASSWORD") or _deployment_password()
    if not password:
        raise RuntimeError(
            "No Exasol password. Set EXASOL_PASSWORD in .env, or point EXASOL_DEPLOYMENT_DIR at a "
            f"deployment whose secrets.json the launcher wrote (looked in {deployment_dir()})."
        )
    return {
        "host": host,
        "port": int(port),
        "user": os.getenv("EXASOL_USER") or dep.get("username") or "sys",
        "password": password,
        "schema": os.getenv("EXASOL_SCHEMA", ""),
        "fingerprint": os.getenv("EXASOL_CERT_FINGERPRINT", "").strip(),
    }


def connect(**overrides) -> pyexasol.ExaConnection:
    """Open a connection to Exasol with TLS verification (see module docstring)."""
    cfg = settings() | overrides
    host, port, fingerprint = cfg.pop("host"), cfg.pop("port"), cfg.pop("fingerprint")
    schema = cfg.pop("schema", "")

    if fingerprint:
        # pyexasol pins the server certificate to this SHA-256 fingerprint.
        dsn = f"{host}/{fingerprint}:{port}"
        ssl_opts: dict = {}
    elif host in LOCAL_HOSTS:
        # Local launcher deployment uses a self-signed certificate. Fine for loopback only.
        dsn = f"{host}:{port}"
        ssl_opts = {"websocket_sslopt": {"cert_reqs": ssl.CERT_NONE}}
    else:
        # Remote host without a fingerprint: use normal certificate validation.
        dsn = f"{host}:{port}"
        ssl_opts = {}

    conn = pyexasol.connect(dsn=dsn, **cfg, **ssl_opts, compression=True)
    if schema:
        conn.execute(f"OPEN SCHEMA {schema}")
    return conn


if __name__ == "__main__":  # quick connectivity check
    s = settings()
    with connect() as c:
        version = c.execute(
            "SELECT PARAM_VALUE FROM EXA_METADATA WHERE PARAM_NAME = 'databaseProductVersion'"
        ).fetchval()
        user = c.execute("SELECT CURRENT_USER").fetchval()
        print(f"Connected to Exasol {version} at {s['host']}:{s['port']} as {user}")
