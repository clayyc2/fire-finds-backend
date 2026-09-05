"""Gate matrix + mocked HTTP for sandbox Sell inventory/offer (no live publish)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from firefinds.clients.ebay import (
    EbayApiError,
    EbayClient,
    EbayListingsDisabled,
    EbayPublishDisabled,
)
from firefinds.config import Settings
from firefinds.listings.sandbox_e2e import (
    FINAL5_V21_SKUS,
    run_sandbox_inventory_offer_e2e,
    write_e2e_reports,
)


def _settings(tmp_path: Path, **kwargs) -> Settings:
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "ebay_client_secret.txt").write_text("SBX-cert\n", encoding="utf-8")
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
        # These tests mock all HTTP. Explicitly permit Sandbox test writes;
        # stored credentials alone no longer bypass dry-run/kill protection.
        dry_run=False,
        global_kill_switch=False,
    )
    base.update(kwargs)
    return Settings(**base)


def _store_refresh(settings: Settings, value: str = "refresh-token-value") -> None:
    path = settings.ebay_user_refresh_token_file
    assert path is not None
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)


class _FakeResp:
    def __init__(self, payload: dict | None, code: int = 200):
        self._payload = payload
        self.status = code

    def read(self) -> bytes:
        if self._payload is None:
            return b""
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_sandbox_inventory_allowed_with_refresh_without_live(tmp_path: Path):
    settings = _settings(tmp_path)
    _store_refresh(settings)
    client = EbayClient(settings)
    client._user_access_token = "access-token"
    client._user_access_token_expires_at = 9e12

    with patch("urllib.request.urlopen", return_value=_FakeResp(None, 204)) as mock_open:
        out = client.create_or_replace_inventory_item(
            "SKU1",
            {"sku": "SKU1", "condition": "NEW", "product": {"title": "T"}},
        )
    assert out["ok"] is True
    assert mock_open.called
    req = mock_open.call_args[0][0]
    assert req.method == "PUT"
    assert "/inventory/v1/inventory_item/SKU1" in req.full_url
    assert "api.sandbox.ebay.com" in req.full_url


@pytest.mark.parametrize("environment", ["sandbox", "production"])
@pytest.mark.parametrize("control", ["dry_run", "global_kill_switch"])
def test_global_controls_block_every_listing_mutation(tmp_path, environment, control):
    settings = _settings(tmp_path, ebay_env=environment, live_listings_enabled=True,
                         ebay_production_enabled=True, ebay_sandbox_publish_enabled=True,
                         **{control: True})
    _store_refresh(settings)
    client = EbayClient(settings)
    with patch("urllib.request.urlopen", side_effect=AssertionError("No HTTP allowed")):
        with pytest.raises(EbayListingsDisabled):
            client.create_offer({"sku": "X"})
        with pytest.raises(EbayListingsDisabled):
            client.create_or_replace_inventory_item("X", {})
        with pytest.raises(EbayPublishDisabled):
            client.publish_offer("offer-id")


def test_sandbox_inventory_refused_without_refresh_or_live(tmp_path: Path):
    settings = _settings(tmp_path)
    client = EbayClient(settings)
    with pytest.raises(EbayListingsDisabled):
        client.create_or_replace_inventory_item("SKU1", {"condition": "NEW"})


def test_publish_refused_when_sandbox_publish_off_even_with_refresh(tmp_path: Path):
    settings = _settings(tmp_path, ebay_sandbox_publish_enabled=False)
    _store_refresh(settings)
    client = EbayClient(settings)
    with pytest.raises(EbayPublishDisabled):
        client.publish_offer("offer-1")


def test_production_sell_locked_without_flags(tmp_path: Path):
    settings = _settings(
        tmp_path,
        ebay_env="production",
        live_listings_enabled=True,
        ebay_production_enabled=False,
    )
    _store_refresh(settings)
    client = EbayClient(settings)
    with pytest.raises(EbayListingsDisabled):
        client.create_offer({"sku": "X", "marketplaceId": "EBAY_CA"})


def test_production_requires_live_even_if_production_enabled(tmp_path: Path):
    settings = _settings(
        tmp_path,
        ebay_env="production",
        live_listings_enabled=False,
        ebay_production_enabled=True,
    )
    _store_refresh(settings)
    client = EbayClient(settings)
    with pytest.raises(EbayListingsDisabled):
        client.create_or_replace_inventory_item("SKU1", {"condition": "NEW"})


def test_create_offer_http_and_api_error_parsing(tmp_path: Path):
    settings = _settings(tmp_path)
    _store_refresh(settings)
    client = EbayClient(settings)
    client._user_access_token = "access-token"
    client._user_access_token_expires_at = 9e12

    with patch(
        "urllib.request.urlopen", return_value=_FakeResp({"offerId": "OID123"})
    ):
        out = client.create_offer(
            {
                "sku": "SKU1",
                "marketplaceId": "EBAY_CA",
                "format": "FIXED_PRICE",
                "categoryId": "112529",
            }
        )
    assert out["offerId"] == "OID123"

    def boom(*_a, **_k):
        raise urllib.error.HTTPError(
            url="https://api.sandbox.ebay.com/sell/inventory/v1/offer",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(
                json.dumps(
                    {
                        "errors": [
                            {
                                "errorId": 25007,
                                "message": "User is not eligible for Business Policy",
                                "longMessage": "User is not eligible for Business Policy",
                                "domain": "API_INVENTORY",
                            }
                        ]
                    }
                ).encode()
            ),
        )

    with patch("urllib.request.urlopen", side_effect=boom):
        with pytest.raises(EbayApiError) as ei:
            client.create_offer({"sku": "SKU1", "marketplaceId": "EBAY_CA"})
    assert ei.value.status == 400
    assert ei.value.error_id == 25007
    assert "Business Policy" in str(ei.value)
    # no raw token leakage
    assert "access-token" not in str(ei.value)


def test_create_or_update_offer_updates_existing(tmp_path: Path):
    settings = _settings(tmp_path)
    _store_refresh(settings)
    client = EbayClient(settings)
    client._user_access_token = "access-token"
    client._user_access_token_expires_at = 9e12

    calls: list[str] = []

    def fake_urlopen(req, timeout=60):
        calls.append(f"{req.method}:{req.full_url}")
        if req.method == "GET":
            return _FakeResp({"offers": [{"offerId": "EXISTING1", "sku": "SKU1",
                                         "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"}]})
        if req.method == "PUT":
            return _FakeResp(None, 204)
        raise AssertionError(req.method)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.create_or_update_offer(
            {"sku": "SKU1", "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"}
        )
    assert out["offerId"] == "EXISTING1"
    assert out["updated"] is True
    assert any(c.startswith("GET:") for c in calls)
    assert any(c.startswith("PUT:") for c in calls)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_offer_lookup_error_never_creates_duplicate(tmp_path: Path, status):
    client = EbayClient(_settings(tmp_path))
    _store_refresh(client.settings)
    with patch.object(client, "get_offers_for_sku", side_effect=EbayApiError("lookup failed", status=status)), \
            patch.object(client, "create_offer") as create, patch.object(client, "update_offer") as update:
        with pytest.raises(EbayApiError):
            client.create_or_update_offer({"sku": "SKU1", "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"})
        create.assert_not_called()
        update.assert_not_called()


@pytest.mark.parametrize("response", [None, {}, {"offers": None}, {"offers": [], "next": "next"},
    {"offers": [], "total": 1}, {"offers": [], "total": False},
    {"offers": [{"offerId": "missing_identity"}]}, {"offers": [{}, {}]},
    {"offers": [{"offerId": "x", "sku": "OTHER", "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"}]}])
def test_ambiguous_offer_lookup_never_mutates(tmp_path: Path, response):
    client = EbayClient(_settings(tmp_path))
    _store_refresh(client.settings)
    with patch.object(client, "get_offers_for_sku", return_value=response), \
            patch.object(client, "create_offer") as create, patch.object(client, "update_offer") as update:
        with pytest.raises(EbayApiError):
            client.create_or_update_offer({"sku": "SKU1", "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"})
        create.assert_not_called()
        update.assert_not_called()


def test_explicit_empty_offer_lookup_can_create(tmp_path: Path):
    client = EbayClient(_settings(tmp_path))
    _store_refresh(client.settings)
    payload = {"sku": "SKU1", "marketplaceId": "EBAY_CA", "format": "FIXED_PRICE"}
    with patch.object(client, "get_offers_for_sku", return_value={"offers": [], "total": 0}), \
            patch.object(client, "create_offer", return_value={"offerId": "new"}) as create:
        assert client.create_or_update_offer(payload) == {"offerId": "new", "updated": False}
        create.assert_called_once_with(payload)


def test_e2e_runner_mocked_inventory_ok_offer_blocked_publish_refused(tmp_path: Path):
    settings = _settings(tmp_path)
    _store_refresh(settings)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    sku = FINAL5_V21_SKUS[0]
    draft = {
        "inventory_item": {
            "sku": sku,
            "condition": "NEW",
            "product": {"title": "Test"},
            "availability": {"shipToLocationAvailability": {"quantity": 1}},
        },
        "offer": {
            "sku": sku,
            "marketplaceId": "EBAY_CA",
            "format": "FIXED_PRICE",
            "categoryId": "placeholder",
            "listingPolicies": {
                "fulfillmentPolicyId": "placeholder",
                "paymentPolicyId": "placeholder",
                "returnPolicyId": "placeholder",
            },
            "pricingSummary": {"price": {"value": "10.00", "currency": "CAD"}},
        },
    }
    (drafts / f"{sku}.ORIGINAL_SUPPLIER.json").write_text(
        json.dumps(draft), encoding="utf-8"
    )

    client = EbayClient(settings)
    client._user_access_token = "access-token"
    client._user_access_token_expires_at = 9e12

    def fake_urlopen(req, timeout=60):
        if "/inventory_item/" in req.full_url and req.method == "PUT":
            return _FakeResp(None, 204)
        if "/offer" in req.full_url:
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=400,
                msg="Bad Request",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(
                    json.dumps(
                        {
                            "errors": [
                                {
                                    "errorId": 25007,
                                    "message": "User is not eligible for Business Policy",
                                    "longMessage": "User is not eligible for Business Policy",
                                }
                            ]
                        }
                    ).encode()
                ),
            )
        raise AssertionError(req.full_url)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        report = run_sandbox_inventory_offer_e2e(
            settings=settings,
            skus=[sku],
            drafts_dir=drafts,
            client=client,
        )
    assert report["summary"]["inventory_ok"] == 1
    assert report["summary"]["offer_ok"] == 0
    assert report["summary"]["publish_refused"] == 1
    assert "Business Policy" in (report["summary"].get("offer_blocker") or "")

    paths = write_e2e_reports(report, reports_dir=tmp_path / "reports")
    assert Path(paths["json"]).is_file()
    assert Path(paths["md"]).is_file()
    md = Path(paths["md"]).read_text(encoding="utf-8")
    assert "Business Policy" in md
    assert "access-token" not in md
