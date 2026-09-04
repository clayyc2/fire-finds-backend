"""Sandbox Sell user OAuth (authorization code → refresh token) — mocked HTTP."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from firefinds.cli.main import main
from firefinds.clients.ebay import (
    SELL_USER_SCOPES,
    EbayClient,
    EbayCredentialsMissing,
    EbayUserOAuthNotConfigured,
)
from firefinds.config import Settings


def _settings(tmp_path: Path, **kwargs) -> Settings:
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    base = dict(
        db_path=tmp_path / "t.db",
        actions_jsonl=tmp_path / "a.jsonl",
        secrets_dir=secrets,
        ebay_env="sandbox",
        ebay_client_id="TestApp-SBX-aaaa",
        ebay_client_secret_file=secrets / "ebay_client_secret.txt",
        ebay_runame="FireFinds-FireFind-SBX-ru123",
        ebay_user_refresh_token_file=secrets / "ebay_user_refresh_token.txt",
        live_listings_enabled=False,
        ebay_sandbox_publish_enabled=False,
        ebay_production_enabled=False,
        supplier_orders_enabled=False,
    )
    base.update(kwargs)
    (secrets / "ebay_client_secret.txt").write_text("SBX-secret-cert\n", encoding="utf-8")
    return Settings(**base)


class _FakeResp:
    def __init__(self, payload: dict, code: int = 200):
        self._payload = payload
        self.status = code

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_build_auth_url_sandbox_minimal_scopes(tmp_path: Path):
    settings = _settings(tmp_path)
    client = EbayClient(settings)
    url = client.build_auth_url()
    assert url.startswith("https://auth.sandbox.ebay.com/oauth2/authorize?")
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    assert qs["client_id"] == ["TestApp-SBX-aaaa"]
    assert qs["redirect_uri"] == ["FireFinds-FireFind-SBX-ru123"]
    assert qs["response_type"] == ["code"]
    scope = qs["scope"][0]
    assert "sell.inventory" in scope
    assert "sell.account" in scope
    assert "sell.fulfillment" in scope
    assert "sell.marketing" not in scope
    for s in SELL_USER_SCOPES:
        assert s in scope


def test_build_auth_url_requires_runame(tmp_path: Path):
    settings = _settings(tmp_path, ebay_runame=None)
    client = EbayClient(settings)
    with pytest.raises(EbayUserOAuthNotConfigured):
        client.build_auth_url()


def test_exchange_code_stores_refresh_mode_600_no_secrets_in_status(
    tmp_path: Path, capsys
):
    settings = _settings(tmp_path)
    client = EbayClient(settings)
    token_payload = {
        "access_token": "ACCESS_SECRET_VALUE_xyz",
        "expires_in": 7200,
        "refresh_token": "REFRESH_SECRET_VALUE_abc",
        "refresh_token_expires_in": 47304000,
        "token_type": "User Access Token",
        "scope": " ".join(SELL_USER_SCOPES),
    }

    with patch("urllib.request.urlopen", return_value=_FakeResp(token_payload)):
        status = client.exchange_code("v%5E1.1%23authcode")

    path = Path(status["refresh_token_path"])
    assert path.is_file()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert path.read_text(encoding="utf-8").strip() == "REFRESH_SECRET_VALUE_abc"
    assert status["refresh_token_present"] is True
    assert status["ok"] is True
    # No secrets in status dict
    blob = json.dumps(status)
    assert "REFRESH_SECRET" not in blob
    assert "ACCESS_SECRET" not in blob
    assert client._user_access_token == "ACCESS_SECRET_VALUE_xyz"


def test_refresh_user_token_and_get_access_token(tmp_path: Path):
    settings = _settings(tmp_path)
    refresh_path = settings.ebay_user_refresh_token_file
    assert refresh_path is not None
    refresh_path.write_text("stored-refresh\n", encoding="utf-8")
    client = EbayClient(settings)

    payload = {
        "access_token": "new-access",
        "expires_in": 7200,
        "token_type": "User Access Token",
    }
    with patch("urllib.request.urlopen", return_value=_FakeResp(payload)) as mock_open:
        token = client.refresh_user_token()
        assert token == "new-access"
        # Second call should use cache (no extra HTTP)
        again = client.get_user_access_token()
        assert again == "new-access"
        assert mock_open.call_count == 1

    # force_refresh hits network again
    with patch("urllib.request.urlopen", return_value=_FakeResp(payload)) as mock_open:
        forced = client.get_user_access_token(force_refresh=True)
        assert forced == "new-access"
        assert mock_open.call_count == 1


def test_refresh_rotates_refresh_token_when_returned(tmp_path: Path):
    settings = _settings(tmp_path)
    path = settings.ebay_user_refresh_token_file
    assert path is not None
    path.write_text("old-refresh\n", encoding="utf-8")
    client = EbayClient(settings)
    payload = {
        "access_token": "a1",
        "expires_in": 1000,
        "refresh_token": "rotated-refresh",
    }
    with patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
        client.refresh_user_token()
    assert path.read_text(encoding="utf-8").strip() == "rotated-refresh"


def test_user_token_status_presence_only(tmp_path: Path):
    settings = _settings(tmp_path)
    client = EbayClient(settings)
    st = client.user_token_status()
    assert st["refresh_token_present"] is False
    assert st["runame_configured"] is True
    path = settings.ebay_user_refresh_token_file
    assert path is not None
    path.write_text("secret-refresh\n", encoding="utf-8")
    st2 = client.user_token_status()
    assert st2["refresh_token_present"] is True
    assert "secret-refresh" not in json.dumps(st2)


def test_http_error_does_not_echo_body(tmp_path: Path):
    settings = _settings(tmp_path)
    client = EbayClient(settings)

    def boom(*_a, **_k):
        raise urllib.error.HTTPError(
            url="https://api.sandbox.ebay.com/identity/v1/oauth2/token",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"error":"invalid_grant","error_description":"secret"}'),
        )

    with patch("urllib.request.urlopen", side_effect=boom):
        with pytest.raises(RuntimeError) as ei:
            client.exchange_code("bad-code")
    assert "400" in str(ei.value)
    assert "secret" not in str(ei.value)
    assert "invalid_grant" not in str(ei.value)


def test_cli_oauth_url_and_status(tmp_path: Path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    secret = settings.ebay_client_secret_file
    assert secret is not None
    monkeypatch.setenv("EBAY_CLIENT_ID", "TestApp-SBX-aaaa")
    monkeypatch.setenv("EBAY_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("EBAY_RUNAME", "FireFinds-FireFind-SBX-ru123")
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv(
        "EBAY_USER_REFRESH_TOKEN_FILE", str(settings.ebay_user_refresh_token_file)
    )
    monkeypatch.setenv("LIVE_LISTINGS_ENABLED", "false")
    monkeypatch.setenv("EBAY_SANDBOX_PUBLISH_ENABLED", "false")
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "false")
    monkeypatch.setenv("EBAY_PRODUCTION_ENABLED", "false")

    rc = main(["ebay-oauth-url"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("https://auth.sandbox.ebay.com/oauth2/authorize?")

    rc = main(["ebay-user-token-status"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["refresh_token_present"] is False
    assert "secret" not in json.dumps(status).lower() or status.get("note")


def test_cli_oauth_exchange(tmp_path: Path, monkeypatch, capsys):
    settings = _settings(tmp_path)
    secret = settings.ebay_client_secret_file
    assert secret is not None
    monkeypatch.setenv("EBAY_CLIENT_ID", "TestApp-SBX-aaaa")
    monkeypatch.setenv("EBAY_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("EBAY_RUNAME", "FireFinds-FireFind-SBX-ru123")
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv(
        "EBAY_USER_REFRESH_TOKEN_FILE", str(settings.ebay_user_refresh_token_file)
    )

    payload = {
        "access_token": "cli-access-SECRET",
        "expires_in": 7200,
        "refresh_token": "cli-refresh-SECRET",
        "token_type": "User Access Token",
    }
    with patch("urllib.request.urlopen", return_value=_FakeResp(payload)):
        rc = main(["ebay-oauth-exchange", "--code", "authcode123"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli-refresh-SECRET" not in out
    assert "cli-access-SECRET" not in out
    data = json.loads(out)
    assert data["refresh_token_stored"] is True
    stored = Path(data["refresh_token_path"]).read_text(encoding="utf-8").strip()
    assert stored == "cli-refresh-SECRET"


def test_redirect_uri_alias(tmp_path: Path, monkeypatch):
    settings = _settings(tmp_path, ebay_runame=None)
    monkeypatch.setenv("EBAY_REDIRECT_URI", "Alias-RuName-SBX")
    # settings already frozen without runame; client falls back to env
    client = EbayClient(settings)
    assert client._resolve_runame() == "Alias-RuName-SBX"


def test_credentials_missing_blocks_auth_url(tmp_path: Path):
    settings = _settings(tmp_path, ebay_client_id=None)
    # remove secret file effect by clearing id
    client = EbayClient(settings)
    with pytest.raises(EbayCredentialsMissing):
        client.build_auth_url()
