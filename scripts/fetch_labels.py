"""Label_Fetcher: download the pinned openFDA label of every Label_Manifest entry into committed snapshots.

    uv run python scripts/fetch_labels.py

This is the only code in the repo that contacts openFDA. It reads `data/reference/label_manifest.json`,
sends one GET per entry (no API key) and, for each response that passes the checks, saves the body
byte-for-byte as `data/reference/labels/<slug>.json` with its Snapshot_Metadata in `<slug>.meta.json`.
A failed entry keeps its previous files. It never opens a database connection.

Exit status: 0 every entry saved, 1 at least one entry failed (each printed with its reason),
2 manifest fault (nothing requested, nothing written).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hackathon26.labels import (  # noqa: E402
    LabelError,
    ManifestEntry,
    SnapshotMetadata,
    check_response,
    load_manifest,
    request_url,
    slug,
    write_metadata,
)

MANIFEST_PATH = ROOT / "data" / "reference" / "label_manifest.json"
LABEL_DIR = ROOT / "data" / "reference" / "labels"

USER_AGENT = "medguard-hackathon-label-fetcher"
SOCKET_TIMEOUT = 30.0  # seconds, per socket operation
READ_LIMIT = 30.0  # seconds, whole request from send to last byte
MIN_SPACING = 1.0  # seconds between the starts of any two attempts (Requirement 7.7)
BACKOFF_429 = 5.0  # seconds to wait after HTTP 429 (Requirement 7.8)
MAX_ATTEMPTS = 4  # one request plus at most 3 repeats on HTTP 429
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


Transport = Callable[[str, dict[str, str]], Response]


def urllib_transport(
    url: str,
    headers: dict[str, str],
    *,
    timeout: float = SOCKET_TIMEOUT,
    read_limit: float = READ_LIMIT,
    clock: Callable[[], float] = time.monotonic,
) -> Response:
    """GET `url` with stdlib urllib. HTTP error statuses come back as a Response, not an exception.

    Raises TimeoutError if the request runs longer than `read_limit` seconds, and OSError (including
    urllib.error.URLError) or http.client.HTTPException if it cannot connect or read.
    """
    started = clock()
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        status = response.getcode()
        chunks = []
        while True:
            if clock() - started > read_limit:
                raise TimeoutError(f"the request ran longer than {read_limit:g} s")
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    return Response(status=status, body=b"".join(chunks))


def utc_now() -> datetime:
    return datetime.now(UTC)


def _transport_failure(error: BaseException) -> str:
    reason = getattr(error, "reason", None)
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
        return f"timed out after {READ_LIMIT:g} s: {error}"
    return f"could not connect or read the response: {type(error).__name__}: {error}"


def _status_failure(status: int) -> str:
    if status == 404:
        return "HTTP 404: openFDA reports no match"
    return f"HTTP {status}, expected 200"


def _save(entry: ManifestEntry, label_dir: Path, url: str, body: bytes, fetched_at: datetime) -> tuple[Path, str]:
    """Write the snapshot and its metadata through `.tmp` files, then `os.replace` both into place."""
    digest = hashlib.sha256(body).hexdigest()
    meta = SnapshotMetadata(request_url=url, fetched_at=fetched_at, sha256=digest)
    stem = slug(entry.generic_name)
    snapshot, metadata = label_dir / f"{stem}.json", label_dir / f"{stem}.meta.json"
    snapshot_tmp, metadata_tmp = label_dir / f"{stem}.json.tmp", label_dir / f"{stem}.meta.json.tmp"
    label_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_tmp.write_bytes(body)
        write_metadata(metadata_tmp, meta)
        os.replace(snapshot_tmp, snapshot)
        os.replace(metadata_tmp, metadata)
    finally:
        snapshot_tmp.unlink(missing_ok=True)
        metadata_tmp.unlink(missing_ok=True)
    return snapshot, digest


def fetch_all(
    entries: Iterable[ManifestEntry],
    label_dir: Path,
    *,
    transport: Transport = urllib_transport,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
    out: TextIO | None = None,
) -> int:
    """Fetch, check and save each entry's label in order. Returns the exit status (0 or 1)."""
    out = out if out is not None else sys.stdout
    label_dir = Path(label_dir)
    headers = {"User-Agent": USER_AGENT}
    entries = list(entries)
    failures: list[tuple[str, str]] = []
    last_start: float | None = None

    for entry in entries:
        url = request_url(entry.set_id)
        reason: str | None = None
        body = b""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if last_start is not None:
                wait = MIN_SPACING - (clock() - last_start)
                if wait > 0:
                    sleep(wait)
            last_start = clock()
            try:
                response = transport(url, dict(headers))
            except (OSError, http.client.HTTPException) as error:
                reason = _transport_failure(error)
                break
            if response.status == 429:
                if attempt < MAX_ATTEMPTS:
                    print(
                        f"{entry.generic_name}: HTTP 429 from openFDA, waiting {BACKOFF_429:g} s "
                        f"(attempt {attempt} of {MAX_ATTEMPTS})",
                        file=out,
                    )
                    sleep(BACKOFF_429)
                    continue
                reason = f"HTTP 429 (rate limited) on all {MAX_ATTEMPTS} attempts"
            elif response.status != 200:
                reason = _status_failure(response.status)
            else:
                body = response.body
            break

        if reason is None:
            try:
                check_response(entry, body)
            except LabelError as error:
                reason = error.check
        if reason is None:
            fetched_at = now().astimezone(UTC).replace(microsecond=0)
            try:
                path, digest = _save(entry, label_dir, url, body, fetched_at)
            except (OSError, ValueError) as error:
                reason = f"could not save the snapshot: {type(error).__name__}: {error}"
            else:
                print(f"saved {entry.generic_name}: sha256 {digest} ({path.relative_to(label_dir.parent)})", file=out)
        if reason is not None:
            failures.append((entry.generic_name, reason))

    if failures:
        print(f"{len(failures)} of {len(entries)} labels failed; their previous files are unchanged:", file=out)
        for name, reason in failures:
            print(f"FAILED {name}: {reason}", file=out)
        return 1
    print(f"all {len(entries)} labels saved under {label_dir}", file=out)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    manifest_path: Path = MANIFEST_PATH,
    label_dir: Path = LABEL_DIR,
    transport: Transport = urllib_transport,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = utc_now,
) -> int:
    parser = argparse.ArgumentParser(
        description="Download the pinned openFDA label of every Label_Manifest entry into data/reference/labels/."
    )
    parser.parse_args(argv)
    try:
        entries = load_manifest(manifest_path)
    except LabelError as error:
        print(f"label manifest fault in {manifest_path}: {error}", file=sys.stderr)
        print("nothing was requested and nothing was written", file=sys.stderr)
        return 2
    return fetch_all(entries, label_dir, transport=transport, clock=clock, sleep=sleep, now=now)


if __name__ == "__main__":
    sys.exit(main())
