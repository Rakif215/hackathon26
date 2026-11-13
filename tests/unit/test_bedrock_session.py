"""The Bedrock session must use the sandbox profile, never the machine's own AWS environment.

The dev machine exports AWS_ACCESS_KEY_ID / AWS_REGION for unrelated accounts. If boto3's default
credential chain picks those up, the app calls the wrong account in a region the event blocks.
"""
import importlib

import pytest

from hackathon26 import bedrock


@pytest.fixture
def sandbox_files(tmp_path, monkeypatch):
    creds = tmp_path / "credentials"
    creds.write_text(
        "[hackathon]\n"
        "aws_access_key_id = AKIASANDBOXPROFILE\n"
        "aws_secret_access_key = sandbox-secret\n"
    )
    config = tmp_path / "config"
    config.write_text("[profile hackathon]\nregion = us-west-2\n")

    # The machine's unrelated environment, which must be ignored.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAUNRELATEDENV")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unrelated-secret")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

    monkeypatch.setenv("SANDBOX_AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("SANDBOX_AWS_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("SANDBOX_AWS_PROFILE", "hackathon")
    monkeypatch.delenv("SANDBOX_AWS_REGION", raising=False)


def test_session_uses_sandbox_profile_not_environment_keys(sandbox_files):
    creds = bedrock.session().get_credentials()
    assert creds.access_key == "AKIASANDBOXPROFILE"


def test_session_region_ignores_shell_aws_region(sandbox_files):
    assert bedrock.session().region_name == "us-west-2"


def test_empty_model_id_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "")
    reloaded = importlib.reload(bedrock)
    assert reloaded.DEFAULT_MODEL == reloaded.SONNET


def test_region_outside_event_allowlist_is_refused(sandbox_files, monkeypatch):
    monkeypatch.setenv("SANDBOX_AWS_REGION", "us-east-1")
    with pytest.raises(RuntimeError, match="us-east-1"):
        bedrock.session()
