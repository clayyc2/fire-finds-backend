import copy
import gzip
import json
from unittest.mock import MagicMock, patch

import pytest

from firefinds.clients.randmar import RandmarClient, SupplierOrdersDisabled
from firefinds.clients.randmar_readonly import ReadOnlyRandmarClient
from firefinds.config import Settings
from firefinds.fulfillment.identity import gtin, inspect_listing, verify_identity


def identities():
    return ({"sku": "6100176", "product": {"upc": ["191628482221"], "mpn": "SU858A", "brand": "HP"}},
            {"RandmarSKU": "6100176", "UPC": "191628482221", "MPN": "SU858A", "ManufacturerName": "HP Canada",
             "ManufacturerId": "25150", "OpportunityOnly": False, "AvailableQuantity": 20, "Price": 118.54, "MAP": 183.83})


def test_hp_alias_requires_both_identifiers_and_exact_manufacturer():
    inventory, supplier = identities()
    assert verify_identity("6100176", inventory, supplier) == "exact_sku_and_gtin"
    for changes in ({"UPC": None}, {"MPN": None}, {"ManufacturerId": "OTHER"}):
        assert verify_identity("6100176", inventory, dict(supplier, **changes)) == "brand_conflict"
    assert verify_identity("6100176", inventory, dict(supplier, MPN="DIFFERENT")) == "mpn_conflict"
    assert verify_identity("6100176", inventory, dict(supplier, UPC="192545175708")) == "upc_conflict"


@pytest.mark.parametrize("product", [[], "invalid", 4, {"upc": "not-a-list"}])
def test_malformed_identity_is_not_verified(product):
    inv, supplier = identities()
    inv["product"] = product
    assert not verify_identity("6100176", inv, supplier).startswith("exact_")


@pytest.mark.parametrize("value", [None, 191628482221, "191628482222", "123", "１２３４５６７８", "NaN"])
def test_gtin_does_not_invent_identifiers(value):
    assert gtin(value) is None


def test_mapping_does_not_authorize_opportunity_only_purchase():
    inv, supplier = identities()
    supplier["OpportunityOnly"] = True
    offer = {"sku": "6100176", "marketplaceId": "EBAY_CA", "status": "PUBLISHED",
             "listing": {"listingId": "1"}, "availableQuantity": 1,
             "pricingSummary": {"price": {"currency": "CAD", "value": "183.83"}}}
    result = inspect_listing(merchant_sku="6100176", listing_id="1", inventory=inv,
                             offers={"offers": [offer]}, supplier=supplier, stock_buffer=2)
    assert result["mapping_verified"] and not result["fulfillment_enabled"]
    assert result["observed_holds"] == ["default_opportunity_not_confirmed"]
    offer["pricingSummary"] = "invalid"
    assert "unknown_price_or_cost" in inspect_listing(merchant_sku="6100176", listing_id="1", inventory=inv,
                             offers={"offers": [offer]}, supplier=supplier, stock_buffer=2)["observed_holds"]


def test_randmar_reader_has_no_cart_or_order_mutation_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("RANDMAR_CLIENT_SECRET", "must-ignore-ambient")
    monkeypatch.setenv("SUPPLIER_ORDERS_ENABLED", "true")
    reader = ReadOnlyRandmarClient(tmp_path, "TEST")
    assert reader._load_credentials() == (None, None)
    base = reader._reseller_path("").rstrip("/")
    with patch.object(RandmarClient, "_request_json", return_value=[]) as request:
        assert reader.get_products_json() == []
        assert reader.list_shipments() == []
        for method, url in [("POST", base + "/Cart/ProcessNew/X"), ("GET", "https://other.invalid/Order/X"),
                            ("DELETE", base + "/Cart/X"), ("POST", base + "/Report/Products/JSON?x=1")]:
            with pytest.raises(SupplierOrdersDisabled):
                reader._request_json(method, url)
        assert request.call_count == 2
    path = tmp_path / "randmar_api_key.txt"
    path.write_text("test-key")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        reader._load_credentials()


def test_supplier_gzip_catalog_is_decoded_without_guessing(monkeypatch):
    client = RandmarClient(Settings())
    monkeypatch.setattr(client, "fetch_token", lambda **kwargs: "fixture")
    response = MagicMock()
    response.headers = {"Content-Encoding": "gzip"}
    response.read.return_value = gzip.compress(json.dumps([{"RandmarSKU": "TEST"}]).encode())
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response):
        assert client.get_products_json() == [{"RandmarSKU": "TEST"}]
