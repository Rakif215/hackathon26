"""Seed_Command CLI: argument handling, offline validation and source scans (offline: no network, no database).

`main` gets a fake `connect_factory` that records every call and every SQL text, so a test can prove that
no connection was opened. The committed inputs are copied to a temporary directory and the module-level
paths of `seed` are pointed there, so each test can break one input without touching the repository.
Requirements 2.10, 3.10, 4.10, 8.2, 8.7, 8.11, 9.11, 9.12, 10.6, 15.1 and 15.4.
"""
import ast
import copy
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hackathon26 import seed
from hackathon26.labels import FETCH_COMMAND, read_metadata, write_metadata

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "hackathon26"
SEED_SOURCE = SRC / "seed.py"
LEGACY_TABLES = ("DRUG_PRODUCT", "PRESCRIPTION", "DISPENSING", "REVIEW_QUEUE")
PURE_MODULES = ("seed.py", "labels.py", "demo_fixture.py", "schema_file.py", "join_verification.py")
BANNED_IMPORTS = ("urllib.request", "http.client", "socket", "boto3", "requests", "hackathon26.bedrock")


class FakeConnection:
    """Records every SQL text sent through `execute`."""

    def __init__(self, factory: "FakeConnect") -> None:
        self._factory = factory

    def execute(self, sql, params=None):
        self._factory.sql.append(sql)
        raise AssertionError(f"unexpected SQL in an offline test: {sql!r}")

    def close(self) -> None:
        pass


class FakeConnect:
    """A `connect_factory` that records each call's keyword arguments and the SQL its connections receive."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.sql: list[str] = []

    def __call__(self, **kwargs) -> FakeConnection:
        self.calls.append(kwargs)
        return FakeConnection(self)


class Inputs:
    """Temporary copies of the committed Demo_Fixture, Label_Manifest and Label_Snapshots."""

    def __init__(self, root: Path) -> None:
        self.fixture = root / "demo_fixture.json"
        self.manifest = root / "label_manifest.json"
        self.labels = root / "labels"
        shutil.copy(seed.FIXTURE_PATH, self.fixture)
        shutil.copy(seed.MANIFEST_PATH, self.manifest)
        shutil.copytree(seed.LABEL_DIR, self.labels)

    def mutate_fixture(self, mutate) -> None:
        data = json.loads(self.fixture.read_text(encoding="utf-8"))
        data = copy.deepcopy(data)
        mutate(data)
        self.fixture.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def inputs(tmp_path, monkeypatch) -> Inputs:
    copied = Inputs(tmp_path)
    monkeypatch.setattr(seed, "FIXTURE_PATH", copied.fixture)
    monkeypatch.setattr(seed, "MANIFEST_PATH", copied.manifest)
    monkeypatch.setattr(seed, "LABEL_DIR", copied.labels)
    return copied


def run(argv: list[str]) -> tuple[int, str, str, FakeConnect]:
    factory, out, err = FakeConnect(), io.StringIO(), io.StringIO()
    code = seed.main(argv, connect_factory=factory, out=out, err=err)
    return code, out.getvalue(), err.getvalue(), factory


# --- Argument handling (Requirements 2.10, 15.4) ---


@pytest.mark.parametrize("argv", [
    ["--reset"],
    ["--reset", "--apply-schema"],
    ["--verify", "--reset"],
    ["--reset", "--apply-schema", "--verify"],
    ["--reset", "--no-such-option"],
])
def test_reset_is_retired_and_exits_2_before_connecting(argv):
    code, out, err, factory = run(argv)
    assert code == 2
    assert factory.calls == [] and factory.sql == []
    assert "--reset is retired" in err
    assert "--apply-schema" in err


def test_reset_is_hidden_from_help():
    code, out, err, factory = run(["--help"])
    assert code == 0
    assert "--apply-schema" in out and "--verify" in out
    assert "--reset" not in out
    assert factory.calls == []


@pytest.mark.parametrize("argv", [["--apply-schema", "--verify"], ["--verify", "--apply-schema"]])
def test_apply_schema_with_verify_cannot_be_combined(argv):
    code, out, err, factory = run(argv)
    assert code == 2
    assert "cannot be combined" in err
    assert factory.calls == [] and factory.sql == []


def test_unknown_option_exits_2_without_connecting():
    code, out, err, factory = run(["--bogus"])
    assert code == 2
    assert "--bogus" in err
    assert factory.calls == []


def test_option_abbreviations_are_not_accepted():
    code, out, err, factory = run(["--apply"])
    assert code == 2
    assert factory.calls == []


def test_script_run_puts_src_on_sys_path_and_reset_stays_offline(tmp_path):
    """`python src/hackathon26/seed.py` must import `hackathon26.*`; `--reset` still exits 2."""
    result = subprocess.run(
        [sys.executable, str(SEED_SOURCE), "--reset"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
    )
    assert result.returncode == 2, result.stderr
    assert "--reset is retired" in result.stderr
    assert "--apply-schema" in result.stderr


# --- Offline validation (Requirements 4.10, 8.2, 8.7, 8.11, 9.11, 9.12, 10.6) ---


def test_committed_inputs_pass_offline_validation():
    validated, problems = seed.validate_offline()
    assert problems == []
    assert validated is not None
    assert set(validated.rows) == set(seed.SEED_OWNED_TABLES)


MODES = [[], ["--apply-schema"]]


def _assert_exit_3(argv, *expected: str) -> str:
    code, out, err, factory = run(argv)
    assert code == 3, (out, err)
    assert factory.calls == [] and factory.sql == []
    for text in expected:
        assert text in err, f"{text!r} not in {err!r}"
    return err


@pytest.mark.parametrize("argv", MODES)
def test_fixture_with_unknown_key_exits_3_naming_the_path(inputs, argv):
    inputs.mutate_fixture(lambda d: d["patient"].update(nickname="Gerda"))
    _assert_exit_3(argv, "patient.nickname")


@pytest.mark.parametrize("argv", MODES)
def test_medication_naming_an_unseeded_drug_exits_3_naming_the_drug(inputs, argv):
    inputs.mutate_fixture(lambda d: d["medications"][0].update(drug="aspirin"))
    _assert_exit_3(argv, "medications[0]", "aspirin")


@pytest.mark.parametrize("argv", MODES)
def test_missing_snapshot_exits_3_naming_the_drug_and_fetch_command(inputs, argv):
    (inputs.labels / "ibuprofen.json").unlink()
    _assert_exit_3(argv, "ibuprofen", FETCH_COMMAND)


@pytest.mark.parametrize("argv", MODES)
def test_missing_metadata_exits_3_naming_the_drug(inputs, argv):
    (inputs.labels / "furosemide.meta.json").unlink()
    _assert_exit_3(argv, "furosemide")


@pytest.mark.parametrize("argv", MODES)
def test_sha256_mismatch_exits_3_naming_the_drug_and_check(inputs, argv):
    snapshot = inputs.labels / "ramipril.json"
    snapshot.write_bytes(snapshot.read_bytes() + b"\n")
    _assert_exit_3(argv, "ramipril", "SHA-256", FETCH_COMMAND)


def test_set_id_differing_from_the_pin_exits_3_naming_the_drug_and_check(inputs):
    snapshot = inputs.labels / "furosemide.json"
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    document["results"][0]["set_id"] = "00000000-0000-0000-0000-000000000000"
    snapshot.write_text(json.dumps(document), encoding="utf-8")
    meta_path = inputs.labels / "furosemide.meta.json"
    meta = read_metadata(meta_path)
    write_metadata(meta_path, type(meta)(meta.request_url, meta.fetched_at,
                                         hashlib.sha256(snapshot.read_bytes()).hexdigest()))
    _assert_exit_3([], "furosemide", "set_id", "pinned set id")


def test_manifest_without_a_demo_drug_exits_3_naming_it(inputs):
    manifest = json.loads(inputs.manifest.read_text(encoding="utf-8"))
    manifest["labels"] = [e for e in manifest["labels"] if e["generic_name"] != "furosemide"]
    inputs.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    _assert_exit_3([], "furosemide")


@pytest.mark.parametrize("argv", MODES)
def test_failed_rule_quote_exits_3_naming_rule_set_id_and_section_type(inputs, argv):
    def change_one_character(d):
        quote = d["risk_rules"][0]["evidence_quote"]
        d["risk_rules"][0]["evidence_quote"] = quote.replace("renal failure", "renal failurE")

    inputs.mutate_fixture(change_one_character)
    rule_name = json.loads(inputs.fixture.read_text(encoding="utf-8"))["risk_rules"][0]["rule_name"]
    _assert_exit_3(argv, "risk_rules[0].evidence_quote", "10.6", rule_name,
                   "01da05d8-e72e-4208-bf92-a5cd929f15ab", "drug_interactions")


def test_wrong_case_required_class_exits_3_naming_rule_and_class(inputs):
    inputs.mutate_fixture(lambda d: d["risk_rules"][0]["required_classes"].__setitem__(1, "ace inhibitor"))
    rule_name = json.loads(inputs.fixture.read_text(encoding="utf-8"))["risk_rules"][0]["rule_name"]
    _assert_exit_3([], rule_name, "'ace inhibitor'")


def test_over_length_value_exits_3_naming_the_column(inputs):
    inputs.mutate_fixture(lambda d: d["consultation"].update(scenario="x" * 201))
    _assert_exit_3([], "consultation.scenario", "8.11")


def test_every_problem_is_printed_not_only_the_first(inputs):
    inputs.mutate_fixture(lambda d: d["medications"][0].update(drug="aspirin"))
    (inputs.labels / "ibuprofen.json").unlink()
    _assert_exit_3([], "aspirin", "ibuprofen")


# --- Source scans (Requirements 3.10, 15.1) ---


def _seed_tree() -> tuple[str, ast.Module]:
    text = SEED_SOURCE.read_text(encoding="utf-8")
    return text, ast.parse(text)


def test_seed_has_no_create_or_alter_table():
    text, _ = _seed_tree()
    assert not re.search(r"\b(CREATE|ALTER)\s+(OR\s+REPLACE\s+)?TABLE\b", text, re.IGNORECASE)


def test_seed_has_no_legacy_row_building():
    text, tree = _seed_tree()
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not names & {"build_products", "build_patients", "build_prescriptions_and_dispensing"}
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "random" not in imported
    assert not re.search(r"\bDDL\s*=", text)


def test_seed_names_legacy_tables_only_inside_schema_apply_code():
    text, tree = _seed_tree()
    allowed: list[range] = [
        range(node.lineno, node.end_lineno + 1)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.lstrip("_").startswith("schema_apply")
    ]
    pattern = re.compile(r"\b(" + "|".join(LEGACY_TABLES) + r")\b")
    offending = [
        (number, line.strip())
        for number, line in enumerate(text.splitlines(), start=1)
        if pattern.search(line) and not any(number in lines for lines in allowed)
    ]
    assert offending == []


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


@pytest.mark.parametrize("module", PURE_MODULES)
def test_seed_side_modules_import_no_network_client(module):
    imported = _imported_modules(SRC / module)
    banned = {
        name for name in imported
        for ban in BANNED_IMPORTS
        if name == ban or name.startswith(ban + ".")
    }
    assert banned == set(), f"{module} imports {sorted(banned)}"


def test_import_scan_catches_from_imports(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("from urllib import request\nfrom hackathon26 import bedrock\nimport socket\n")
    imported = _imported_modules(sample)
    assert {"urllib.request", "hackathon26.bedrock", "socket"} <= imported


def test_importing_seed_does_not_import_the_database_helper():
    """The default connect_factory resolves `hackathon26.db.connect` lazily, so tests resolve no credentials."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import hackathon26.seed; print('hackathon26.db' in sys.modules)"],
        capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
