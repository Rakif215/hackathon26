"""Amazon Bedrock client for the event AWS account.

Verified working in us-west-2 (Oregon) with Claude models already enabled — no access
request needed.

Two things to know:

1. Reasoning models (Opus 5.5 and friends) put a `reasoningContent` block FIRST in the
   response. `content[0]["text"]` is therefore often absent. Always pick the text block
   out of the list, which `_extract_text` does.
2. The event caps Bedrock at **1 request/second**. `_RateLimiter` enforces that, so don't
   bypass it or fan out parallel calls.

Credentials: `session()` uses only the sandbox profile (SANDBOX_AWS_* in `.env`). It never falls
back to the machine's AWS_* environment variables, which may point at unrelated accounts and
regions the event blocks.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import boto3
import botocore.session
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

# Event rule: only Oregon and Ireland are allowed.
ALLOWED_REGIONS = {"us-west-2", "eu-west-1"}


def region() -> str:
    name = os.getenv("SANDBOX_AWS_REGION", "us-west-2")
    if name not in ALLOWED_REGIONS:
        raise RuntimeError(
            f"SANDBOX_AWS_REGION={name} is not allowed by the event; use one of {sorted(ALLOWED_REGIONS)}."
        )
    return name


def session() -> boto3.Session:
    """A boto3 session pinned to the sandbox profile and region.

    Setting the profile on the botocore session (not via AWS_PROFILE) makes botocore drop the
    environment-variable credential provider, so stray AWS_ACCESS_KEY_ID values are ignored.
    """
    core = botocore.session.Session()
    for var, setting in (
        ("SANDBOX_AWS_CONFIG_FILE", "config_file"),
        ("SANDBOX_AWS_CREDENTIALS_FILE", "credentials_file"),
    ):
        if path := os.getenv(var):
            core.set_config_variable(setting, str(Path(path).expanduser()))
    core.set_config_variable("profile", os.getenv(
        "SANDBOX_AWS_PROFILE", "hackathon"))
    return boto3.Session(botocore_session=core, region_name=region())


# Inference-profile ids (the "us." prefix is required for these models).
OPUS = "us.anthropic.claude-opus-5-5"
SONNET = "us.anthropic.claude-sonnet-5-5"
HAIKU = "us.anthropic.claude-haiku-5-5"

DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_ID", "").strip(
) or SONNET  # empty in .env means default

# Event rule: stay under 1 request per second, account-wide.
_MIN_INTERVAL = 1.05


class _RateLimiter:
    def __init__(self, min_interval: float = _MIN_INTERVAL) -> None:
        self._min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


_limiter = _RateLimiter()
_client = None
_guarded_client = None


def client():
    global _client
    if _client is None:
        _client = session().client("bedrock-runtime")
    return _client


def _extract_text(message: dict) -> str:
    """Join the text blocks, skipping reasoningContent. See note 1 above."""
    return "".join(
        block["text"] for block in message.get("content", []) if "text" in block
    ).strip()


def guarded_converse(prompt: str, *, system: str, guardrail_id: str,
                     guardrail_version: str, model_id: str = DEFAULT_MODEL) -> dict:
    """Bounded guarded call; shares pacing with ask(), with no hidden SDK retries."""
    global _guarded_client
    if _guarded_client is None:
        _guarded_client = session().client("bedrock-runtime", config=Config(
            connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1},
        ))
    _limiter.wait()
    return _guarded_client.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"guardContent": {"text": {"text": prompt}}}]}],
        inferenceConfig={"maxTokens": 2048},
        guardrailConfig={"guardrailIdentifier": guardrail_id, "guardrailVersion": guardrail_version, "trace": "enabled"},
    )


def ask(
    prompt: str,
    *,
    system: str | None = None,
    model_id: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    temperature: float | None = None,
) -> str:
    """Single-turn prompt. Rate-limited to respect the event cap.

    `temperature` is rejected by the 5.x models ("deprecated for this model"), so it is
    omitted unless explicitly passed for an older model.
    """
    inference_config: dict = {"maxTokens": max_tokens}
    if temperature is not None:
        inference_config["temperature"] = temperature

    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": inference_config,
    }
    if system:
        kwargs["system"] = [{"text": system}]

    _limiter.wait()
    response = client().converse(**kwargs)
    return _extract_text(response["output"]["message"])


if __name__ == "__main__":  # smoke test
    print(f"region={region()} model={DEFAULT_MODEL}")
    print(ask("Reply with exactly: BEDROCK OK"))
