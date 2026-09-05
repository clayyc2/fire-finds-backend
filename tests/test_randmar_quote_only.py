import pytest

from firefinds.clients.randmar import RandmarClient, SupplierOrdersDisabled
from firefinds.clients.randmar_quote import QuoteOnlyRandmarClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(RandmarClient, "_request_json", lambda self, method, url, **kw: (method, url))
    return QuoteOnlyRandmarClient(tmp_path, "TEST", cart_names=["ff-quote-test"])


@pytest.mark.parametrize("method,path", [
    ("GET", "/Cart/ff-quote-test"), ("DELETE", "/Cart/ff-quote-test"),
    ("POST", "/Cart/ShippingMethods/ff-quote-test"),
    ("POST", "/Cart/AddItem/ff-quote-test/R1/DefaultOpportunity?quantity=1"),
    ("GET", "/Product/R1"), ("GET", "/Account/General"), ("GET", "/Manufacturer/123")])
def test_only_owned_quotes_and_reads(client, method, path):
    url = client._reseller_path(path)
    assert client._request_json(method, url) == (method, url)


@pytest.mark.parametrize("method,path", [
    ("POST", "/Cart/ProcessNew/ff-quote-test"), ("DELETE", "/Cart/someone-else"),
    ("GET", "/Cart/someone-else"), ("POST", "/Cart/ShippingMethods/someone-else"),
    ("POST", "/Cart/AddItem/ff-quote-test/R1/DefaultOpportunity?quantity=0"),
    ("POST", "/Cart/AddItem/ff-quote-test/R1/DefaultOpportunity?quantity=101"),
    ("POST", "/Cart/AddItem/ff-quote-test/R1/DefaultOpportunity?quantity=1&quantity=2"),
    ("POST", "/Cart/AddItem/ff-quote-test/R1/DefaultOpportunity?quantity=1&extra=true"),
    ("PUT", "/Account/General"), ("GET", "/Product/R1/extra")])
def test_writes_and_foreign_carts_refused(client, method, path):
    with pytest.raises(SupplierOrdersDisabled):
        client._request_json(method, client._reseller_path(path))


def test_even_direct_process_call_is_disabled(client):
    with pytest.raises(SupplierOrdersDisabled):
        client.process_cart("ff-quote-test", {})
