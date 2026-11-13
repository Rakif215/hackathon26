"""Amazon Bedrock client for the event AWS account.

Verified working in us-west-2 (Oregon) with Claude models already enabled — no access
request needed.

Two things to know:

1. Reasoning models (Opus 5.5 and friends) put a `reasoningContent` block FIRST in the
   response. `content[0]["text"]` is therefore often absent. Always pick the text block
   out of the list, which `_extract_text` does.
2. The event caps Bedrock at **1 request/second**. `_RateLimiter` enforces that, so don't
   bypass it or fan out parallel calls.
"""

from __future__ import annotations

import os
import threading
import time

import boto3

REGION = os.getenv("AWS_REGION", "us-west-2")

# Inference-profile ids (the "us." prefix is required for these models).
OPUS = "us.anthropic.claude-opus-5-5"
SONNET = "us.anthropic.claude-sonnet-5-5"
HAIKU = "us.anthropic.claude-haiku-5-5"

DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_ID", SONNET)

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


def client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


def _extract_text(message: dict) -> str:
    """Join the text blocks, skipping reasoningContent. See note 1 above."""
    return "".join(
        block["text"] for block in message.get("content", []) if "text" in block
    ).strip()


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
    print(f"region={REGION} model={DEFAULT_MODEL}")
    print(ask("Reply with exactly: BEDROCK OK"))
