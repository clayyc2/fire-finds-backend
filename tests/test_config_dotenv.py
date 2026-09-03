"""Dotenv parsing and Settings.from_env client_id resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from firefinds.config import (
    DEFAULT_RANDMAR_CLIENT_ID,
    Settings,
    load_dotenv,
    parse_dotenv_line,
    parse_dotenv_value,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("plain", "plain"),
        ('"Fire Finds catalog read"', "Fire Finds catalog read"),
        ("'Fire Finds catalog read'", "Fire Finds catalog read"),
        ("Fire Finds catalog read", "Fire Finds catalog read"),
        ("  spaced  ", "spaced"),
    ],
)
def test_parse_dotenv_value(raw: str, expected: str):
    assert parse_dotenv_value(raw) == expected


@pytest.mark.parametrize(
    "line,expected",
    [
        ("", None),
        ("# comment", None),
        ("NOEQUALS", None),
        ("RANDMAR_CLIENT_ID=Fire Finds catalog read", ("RANDMAR_CLIENT_ID", "Fire Finds catalog read")),
        ('RANDMAR_CLIENT_ID="Fire Finds catalog read"', ("RANDMAR_CLIENT_ID", "Fire Finds catalog read")),
        ("RANDMAR_CLIENT_ID='Fire Finds catalog read'", ("RANDMAR_CLIENT_ID", "Fire Finds catalog read")),
        ("export FOO=bar baz", ("FOO", "bar baz")),
        ("MIN_CONTRIBUTION_PROFIT_CAD=8", ("MIN_CONTRIBUTION_PROFIT_CAD", "8")),
    ],
)
def test_parse_dotenv_line(line: str, expected: tuple[str, str] | None):
    assert parse_dotenv_line(line) == expected


def test_load_dotenv_unquoted_spaced_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RANDMAR_CLIENT_ID=Fire Finds catalog read\n"
        "OTHER=keep\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("RANDMAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    monkeypatch.setenv("OTHER", "already-set")
    applied = load_dotenv(env_file, override=False)
    assert applied["RANDMAR_CLIENT_ID"] == "Fire Finds catalog read"
    assert "OTHER" not in applied  # already set, no override
    import os

    assert os.environ["RANDMAR_CLIENT_ID"] == "Fire Finds catalog read"
    assert os.environ["OTHER"] == "already-set"


def test_load_dotenv_quoted_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    env_file.write_text('RANDMAR_CLIENT_ID="Fire Finds catalog read"\n', encoding="utf-8")
    monkeypatch.delenv("RANDMAR_CLIENT_ID", raising=False)
    applied = load_dotenv(env_file, override=False)
    assert applied["RANDMAR_CLIENT_ID"] == "Fire Finds catalog read"


def test_from_env_default_client_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When CLIENT_ID unset and no secrets file, use DEFAULT_RANDMAR_CLIENT_ID."""
    monkeypatch.delenv("RANDMAR_CLIENT_ID", raising=False)
    secrets = tmp_path / "empty_secrets"
    secrets.mkdir()
    monkeypatch.setenv("RANDMAR_SECRETS_DIR", str(secrets))
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(tmp_path / "a.jsonl"))
    # Avoid loading the real project .env CLIENT_ID during this test
    monkeypatch.setattr(
        "firefinds.config.load_dotenv",
        lambda *a, **k: {},
    )
    settings = Settings.from_env()
    assert settings.randmar_client_id == DEFAULT_RANDMAR_CLIENT_ID


def test_from_env_reads_client_id_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("RANDMAR_CLIENT_ID", raising=False)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "randmar_client_id.txt").write_text(
        "Fire Finds catalog read\n", encoding="utf-8"
    )
    monkeypatch.setenv("RANDMAR_SECRETS_DIR", str(secrets))
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(tmp_path / "a.jsonl"))
    monkeypatch.setattr("firefinds.config.load_dotenv", lambda *a, **k: {})
    settings = Settings.from_env()
    assert settings.randmar_client_id == "Fire Finds catalog read"


def test_from_env_loads_project_dotenv_unquoted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Settings.from_env should load .env so unquoted spaced CLIENT_ID works."""
    monkeypatch.delenv("RANDMAR_CLIENT_ID", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RANDMAR_CLIENT_ID=Fire Finds catalog read\n",
        encoding="utf-8",
    )
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv("RANDMAR_SECRETS_DIR", str(secrets))
    monkeypatch.setenv("FIREFINDS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("FIREFINDS_ACTIONS_JSONL", str(tmp_path / "a.jsonl"))

    def _load(path=None, override=False):
        return load_dotenv(env_file, override=override)

    monkeypatch.setattr("firefinds.config.load_dotenv", _load)
    settings = Settings.from_env()
    assert settings.randmar_client_id == "Fire Finds catalog read"
