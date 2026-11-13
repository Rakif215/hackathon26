"""Unit tests for the Label_Fetcher, `scripts/fetch_labels.py` (offline: fake transport, clock, sleep, now).

Requirements 7.3-7.9, 7.11-7.14 and 16.2. No test here contacts openFDA. The `urllib_transport` tests talk
only to a throwaway HTTP server on 127.0.0.1.
"""

import ast
import hashlib
import http.server
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hackathon26.labels import ManifestEntry, read_metadata, request_url

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fetch_labels.py"


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "fetch_labels_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


fetch_labels = _load_script()
Response = fetch_labels.Response

# Synthetic set ids, valid in form only. They identify no real openFDA document.
SET_IDS = {
    "ramipril": "01da05d8-e72e-4208-bf92-a5cd929f15ab",
    "metoprolol succinate": "aaaaaaaa-2222-4333-8444-bbbbbbbbbbbb",
    "furosemide": "22222222-3333-4444-8555-666666666666",
    "ibuprofen": "33333333-4444-4555-8666-777777777777",
    "spironolactone": "44444444-5555-4666-8777-888888888888",
}
FETCHED_AT = datetime(2026, 11, 13, 21, 4, 17, 654321, tzinfo=UTC)


def entries(*names):
    return [ManifestEntry(generic_name=n, set_id=SET_IDS[n], position=i) for i, n in enumerate(names, start=1)]


DEMO = entries("ramipril", "metoprolol succinate", "furosemide", "ibuprofen")


def label_body(entry, *, total=1, results=None, set_id=None, generic=None):
    """A minimal openFDA-shaped body. Odd spacing and key order prove the save is byte-for-byte."""
    if results is None:
        results = [
            {
                "set_id": set_id or entry.set_id,
                "openfda": {"generic_name": [generic or entry.generic_name.upper()]},
                "drug_interactions": ["Synthetic text \u00e9 for tests."],
            }
        ]
    document = {"results": results, "meta": {
        "results": {"total": total, "skip": 0, "limit": 1}}}
    return (json.dumps(document, ensure_ascii=False, indent=3) + "\n\n").encode("utf-8")


class FakeTime:
    """Monotonic clock that only `sleep` (and the fake transport) advance."""

    def __init__(self):
        self.t = 100.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.t += seconds


class FakeTransport:
    """Answers each call from a per-URL script. Each item is a Response or an exception to raise."""

    def __init__(self, fake_time, script, duration=0.25):
        self.time = fake_time
        self.script = {url: list(items) for url, items in script.items()}
        self.duration = duration
        self.calls = []  # (url, headers, start, end)

    def __call__(self, url, headers):
        start = self.time.t
        self.time.t += self.duration
        self.calls.append((url, dict(headers), start, self.time.t))
        item = self.script[url].pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ok(entry, **kwargs):
    return Response(200, label_body(entry, **kwargs))


def run(label_dir, script, entries_=DEMO):
    fake_time = FakeTime()
    transport = FakeTransport(fake_time, {request_url(
        e.set_id): items for e, items in script.items()})
    out = io.StringIO()
    status = fetch_labels.fetch_all(
        entries_,
        label_dir,
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        now=lambda: FETCHED_AT,
        out=out,
    )
    return status, out.getvalue(), transport, fake_time


def all_ok(entries_=DEMO):
    return {e: [ok(e)] for e in entries_}


def snapshot_files(label_dir):
    return sorted(p.relative_to(label_dir).as_posix() for p in label_dir.rglob("*") if p.is_file())


# --- Requests (7.3, 7.4, 7.12) -------------------------------------------------------------------------


def test_one_get_per_entry_in_manifest_order_without_api_key(tmp_path):
    with_optional = DEMO + entries("spironolactone")
    status, _, transport, _ = run(
        tmp_path, all_ok(with_optional), with_optional)

    assert status == 0
    assert [url for url, *
            _ in transport.calls] == [request_url(e.set_id) for e in with_optional]
    for url, headers, *_ in transport.calls:
        assert headers == {"User-Agent": "medguard-hackathon-label-fetcher"}
        assert "api_key" not in url.lower()
        # a single query parameter: the set_id search
        assert url.count("=") == 1


# --- Save, metadata and output (7.5, 7.6) --------------------------------------------------------------


def test_saves_body_byte_for_byte_with_metadata_and_prints_name_and_sha256(tmp_path):
    bodies = {e: label_body(e) for e in DEMO}
    status, output, _, _ = run(
        tmp_path, {e: [Response(200, b)] for e, b in bodies.items()})

    assert status == 0
    for e, body in bodies.items():
        stem = fetch_labels.slug(e.generic_name)
        assert (tmp_path / f"{stem}.json").read_bytes() == body
        digest = hashlib.sha256(body).hexdigest()
        meta = read_metadata(tmp_path / f"{stem}.meta.json")
        assert meta.request_url == request_url(e.set_id)
        assert meta.fetched_at == FETCHED_AT.replace(microsecond=0)
        assert meta.sha256 == digest
        assert any(
            e.generic_name in line and digest in line for line in output.splitlines())
    assert (tmp_path / "metoprolol-succinate.json").exists()


# --- Spacing and 429 back-off (7.7, 7.8) ---------------------------------------------------------------


def test_attempt_starts_are_at_least_one_second_apart_retries_included(tmp_path):
    first, second = DEMO[0], DEMO[1]
    script = all_ok()
    script[first] = [Response(429, b""), ok(first)]
    script[second] = [Response(429, b""), Response(429, b""), ok(second)]
    status, _, transport, _ = run(tmp_path, script)

    assert status == 0
    starts = [start for *_, start, _ in transport.calls]
    assert len(starts) == 7
    assert all(b - a >= 1.0 for a, b in zip(starts, starts[1:]))


def test_429_waits_at_least_five_seconds_and_retries_the_same_request(tmp_path):
    first = DEMO[0]
    script = all_ok()
    script[first] = [Response(429, b"slow down"), ok(first)]
    status, _, transport, _ = run(tmp_path, script)

    assert status == 0
    (url0, _, _, end0), (url1, _, start1,
                         _) = transport.calls[0], transport.calls[1]
    assert url0 == url1 == request_url(first.set_id)
    assert start1 - end0 >= 5.0


def test_429_stops_after_four_attempts_keeps_old_files_and_continues(tmp_path):
    first = DEMO[0]
    (tmp_path / "ramipril.json").write_bytes(b"old snapshot")
    (tmp_path / "ramipril.meta.json").write_bytes(b"old metadata")
    script = all_ok()
    script[first] = [Response(429, b"")] * 5
    status, output, transport, _ = run(tmp_path, script)

    urls = [url for url, *_ in transport.calls]
    assert urls.count(request_url(first.set_id)) == 4
    assert len(urls) == 4 + 3  # the other three entries still ran
    assert status == 1
    assert (tmp_path / "ramipril.json").read_bytes() == b"old snapshot"
    assert (tmp_path / "ramipril.meta.json").read_bytes() == b"old metadata"
    assert "ramipril" in output and "429" in output
    assert (tmp_path / "furosemide.json").exists()


# --- Each failure kind keeps old files and the run continues (7.9) ------------------------------------

FAILURES = {
    "other status": (Response(500, b"server error"), "HTTP 500"),
    "404 no match": (Response(404, b'{"error": {"code": "NOT_FOUND"}}'), "404"),
    "zero results": ("zero", "total"),
    "timeout": (TimeoutError("timed out"), "timed out"),
    "connection error": (ConnectionRefusedError("refused"), "connect"),
    "invalid json": (Response(200, b"<html>not json</html>"), "not valid JSON"),
    "wrong set id": ("wrong-set-id", "set_id"),
    "generic name mismatch": ("wrong-name", "generic_name"),
}


def failing_item(kind, entry):
    item = FAILURES[kind][0]
    if item == "zero":
        return Response(200, label_body(entry, total=0, results=[]))
    if item == "wrong-set-id":
        return ok(entry, set_id="99999999-9999-4999-8999-999999999999")
    if item == "wrong-name":
        return ok(entry, generic="LISINOPRIL")
    return item


@pytest.mark.parametrize("kind", sorted(FAILURES))
@pytest.mark.parametrize("had_files", [True, False], ids=["old-files", "no-files"])
def test_failure_keeps_existing_files_does_not_retry_and_continues(tmp_path, kind, had_files):
    bad = DEMO[1]  # metoprolol succinate
    if had_files:
        (tmp_path / "metoprolol-succinate.json").write_bytes(b"old snapshot")
        (tmp_path / "metoprolol-succinate.meta.json").write_bytes(b"old metadata")
    script = all_ok()
    script[bad] = [failing_item(kind, bad)]
    status, output, transport, _ = run(tmp_path, script)

    assert status == 1
    urls = [url for url, *_ in transport.calls]
    assert urls == [request_url(e.set_id)
                    for e in DEMO]  # no retry, every entry tried
    if had_files:
        assert (tmp_path / "metoprolol-succinate.json").read_bytes() == b"old snapshot"
        assert (
            tmp_path / "metoprolol-succinate.meta.json").read_bytes() == b"old metadata"
    else:
        assert not (tmp_path / "metoprolol-succinate.json").exists()
        assert not (tmp_path / "metoprolol-succinate.meta.json").exists()
    for good in ("ramipril", "furosemide", "ibuprofen"):
        assert (
            tmp_path / f"{good}.json").exists() and (tmp_path / f"{good}.meta.json").exists()
    failed_lines = [line for line in output.splitlines(
    ) if "metoprolol succinate" in line and "FAILED" in line]
    assert failed_lines and FAILURES[kind][1] in failed_lines[-1]
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_every_failed_entry_is_printed_with_its_reason(tmp_path):
    script = all_ok()
    script[DEMO[0]] = [Response(503, b"")]
    script[DEMO[3]] = [TimeoutError("timed out")]
    status, output, _, _ = run(tmp_path, script)

    assert status == 1
    summary = output[output.index("FAILED"):]
    assert "ramipril" in summary and "HTTP 503" in summary
    assert "ibuprofen" in summary and "timed out" in summary


# --- Exit codes (7.13, 7.14) ---------------------------------------------------------------------------


def test_exit_zero_when_every_entry_saved(tmp_path):
    status, output, _, _ = run(tmp_path, all_ok())
    assert status == 0
    assert "FAILED" not in output
    assert snapshot_files(tmp_path) == sorted(
        f"{fetch_labels.slug(e.generic_name)}{suffix}" for e in DEMO for suffix in (".json", ".meta.json")
    )


def manifest_labels(*names):
    return [{"generic_name": n, "set_id": SET_IDS[n]} for n in names]


@pytest.mark.parametrize(
    "labels",
    [
        manifest_labels("ramipril", "furosemide", "ibuprofen"),
        manifest_labels("ramipril", "ramipril",
                        "metoprolol succinate", "furosemide", "ibuprofen"),
        manifest_labels(*(e.generic_name for e in DEMO))
        + [{"generic_name": "lisinopril", "set_id": SET_IDS["spironolactone"]}],
        [{"generic_name": "ramipril", "set_id": SET_IDS["ramipril"].upper()}]
        + manifest_labels("metoprolol succinate", "furosemide", "ibuprofen"),
    ],
    ids=["missing-demo-drug", "duplicate", "unknown-drug", "uppercase-set-id"],
)
def test_manifest_fault_exits_2_before_any_request_and_writes_nothing(tmp_path, capsys, labels):
    manifest = tmp_path / "label_manifest.json"
    manifest.write_text(json.dumps({"labels": labels}), encoding="utf-8")
    label_dir = tmp_path / "labels"

    def transport(url, headers):
        raise AssertionError("no request may be sent for a faulty manifest")

    status = fetch_labels.main(
        [], manifest_path=manifest, label_dir=label_dir, transport=transport)

    assert status == 2
    assert not label_dir.exists()
    printed = capsys.readouterr()
    assert "manifest" in (printed.out + printed.err).lower()


def test_main_fetches_every_manifest_entry_and_exits_zero(tmp_path, capsys):
    manifest = tmp_path / "label_manifest.json"
    manifest.write_text(json.dumps(
        {"labels": [{"generic_name": e.generic_name, "set_id": e.set_id} for e in DEMO]}))
    fake_time = FakeTime()
    transport = FakeTransport(
        fake_time, {request_url(e.set_id): [ok(e)] for e in DEMO})

    status = fetch_labels.main(
        [],
        manifest_path=manifest,
        label_dir=tmp_path / "labels",
        transport=transport,
        clock=fake_time.clock,
        sleep=fake_time.sleep,
        now=lambda: FETCHED_AT,
    )

    assert status == 0
    assert len(transport.calls) == 4
    assert len(snapshot_files(tmp_path / "labels")) == 8


# --- Writes only under the label directory, atomically (7.11) -----------------------------------------


def test_writes_go_through_tmp_files_and_os_replace_inside_the_label_dir(tmp_path, monkeypatch):
    label_dir = tmp_path / "data" / "reference" / "labels"
    replaced = []
    real_replace = os.replace

    def recording_replace(src, dst):
        replaced.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(fetch_labels.os, "replace", recording_replace)
    status, _, _, _ = run(label_dir, all_ok())

    assert status == 0
    assert len(replaced) == 8
    for src, dst in replaced:
        assert src.parent == dst.parent == label_dir
        assert src.name == dst.name + ".tmp"
    every_file = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert every_file and all(p.parent == label_dir for p in every_file)
    assert not any(p.name.endswith(".tmp") for p in every_file)


def test_default_paths_are_under_data_reference_and_not_gitignored():
    assert fetch_labels.LABEL_DIR == ROOT / "data" / "reference" / "labels"
    assert fetch_labels.MANIFEST_PATH == ROOT / \
        "data" / "reference" / "label_manifest.json"
    samples = [
        "data/reference/labels/ramipril.json",
        "data/reference/labels/ramipril.meta.json",
        "data/reference/labels/metoprolol-succinate.json",
    ]
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", *samples], cwd=ROOT, capture_output=True, text=True
    )
    assert ignored.returncode == 1, f"gitignored: {ignored.stdout}"


# --- No database (7.11, 16.2) --------------------------------------------------------------------------


def test_script_never_imports_hackathon26_db():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(
                f"{node.module}.{alias.name}" for alias in node.names)
    assert not any(name == "hackathon26.db" or name.startswith(
        "hackathon26.db.") for name in imported)
    assert not any(name.split(".")[0] in {
                   "pyexasol", "requests", "httpx", "boto3"} for name in imported)

    probe = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('probe', {str(SCRIPT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['probe'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(sorted(m for m in sys.modules if m == 'hackathon26.db' or m.startswith('pyexasol')))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


# --- The real stdlib transport, against a local server only --------------------------------------------


@pytest.fixture
def local_server(monkeypatch):
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    seen = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen["path"] = self.path
            seen["user_agent"] = self.headers.get("User-Agent")
            status = 429 if "rate" in self.path else 200
            body = b'{"chunked": "' + b"x" * 200_000 + b'"}'
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()
    server.server_close()


def test_urllib_transport_returns_status_and_exact_body(local_server):
    base, seen = local_server
    response = fetch_labels.urllib_transport(
        f"{base}/ok", {"User-Agent": fetch_labels.USER_AGENT})
    assert response.status == 200
    assert response.body == b'{"chunked": "' + b"x" * 200_000 + b'"}'
    assert seen == {"path": "/ok",
                    "user_agent": "medguard-hackathon-label-fetcher"}


def test_urllib_transport_returns_http_errors_as_responses(local_server):
    base, _ = local_server
    response = fetch_labels.urllib_transport(
        f"{base}/rate", {"User-Agent": fetch_labels.USER_AGENT})
    assert response.status == 429


def test_urllib_transport_aborts_a_read_that_runs_past_the_limit(local_server):
    base, _ = local_server
    # each clock reading is 31 s after the previous one
    ticks = iter(range(0, 10_000, 31))
    with pytest.raises(TimeoutError, match="30"):
        fetch_labels.urllib_transport(
            f"{base}/ok", {"User-Agent": fetch_labels.USER_AGENT}, clock=lambda: float(next(ticks))
        )


def test_transport_uses_30_second_limits():
    assert fetch_labels.SOCKET_TIMEOUT == 30.0
    assert fetch_labels.READ_LIMIT == 30.0
