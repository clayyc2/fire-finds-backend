from pathlib import Path

import pytest

from firefinds.clients.ebay import EbayClient, EbayListingsDisabled
from firefinds.clients.ebay_readonly import ReadOnlyEbayClient


@pytest.mark.parametrize("environment", ["sandbox", "production"])
def test_inspection_never_adopts_ambient_gates_or_credentials(tmp_path, monkeypatch, environment):
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "ambient-wrong-environment")
    monkeypatch.setenv("LIVE_LISTINGS_ENABLED", "true")
    monkeypatch.setenv("EBAY_PRODUCTION_ENABLED", "true")
    monkeypatch.setenv("GLOBAL_KILL_SWITCH", "false")
    client = ReadOnlyEbayClient(environment, tmp_path)
    assert client.settings.dry_run and client.settings.global_kill_switch
    assert not client.settings.live_listings_enabled
    assert not client.settings.ebay_production_enabled
    assert client._sell_base() == ("https://api.ebay.com/sell" if environment == "production"
                                   else "https://api.sandbox.ebay.com/sell")
    assert client._load_credentials() == (None, None)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(EbayListingsDisabled):
            client._sell_json(method, "/inventory/v1/offer")
    with pytest.raises(EbayListingsDisabled):
        client.publish_offer("offer")
    with pytest.raises(EbayListingsDisabled):
        client.create_or_replace_inventory_item("sku", {})


def test_inspection_uses_exact_private_pair(tmp_path, monkeypatch):
    for key in ("client_id", "client_secret"):
        path = tmp_path / f"ebay_{key}_sandbox.txt"
        path.write_text(key)
        path.chmod(0o600)
    client = ReadOnlyEbayClient("sandbox", tmp_path)
    assert client._load_credentials() == ("client_id", "client_secret")
    monkeypatch.setattr(EbayClient, "_sell_json", lambda self, method, path, **kwargs: {"offers": []})
    assert client.get_offers_for_sku("sku") == {"offers": []}
    (tmp_path / "ebay_client_secret_sandbox.txt").chmod(0o644)
    with pytest.raises(ValueError):
        client._load_credentials()


def test_requires_explicit_environment(tmp_path):
    with pytest.raises(ValueError):
        ReadOnlyEbayClient("unknown", tmp_path)
