from decimal import Decimal as D
import io

import pytest

from firefinds.clients.ebay_readonly import ReadOnlyEbayClient
from firefinds.engine.remaining_capacity import parse_remaining_capacity, available_after_reservations


def body(quantity="4952", amount="60753.98", currency="CAD", ack="Success"):
    return (f'<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>{ack}</Ack><Summary>'
            f'<QuantityLimitRemaining>{quantity}</QuantityLimitRemaining>'
            f'<AmountLimitRemaining currencyID="{currency}">{amount}</AmountLimitRemaining>'
            '</Summary></GetMyeBaySellingResponse>').encode()


def test_remaining_is_not_headline_cap_and_reservations_reduce_both():
    snap = parse_remaining_capacity(body(), observed_at=1000)
    assert snap["complete"]
    assert available_after_reservations(snap, reserved_quantity=2, reserved_value_cad=D(300), now=1010) == (4950, D("60453.98"))
    assert available_after_reservations(snap, now=1061) is None
    assert available_after_reservations(snap, now=999) is None


@pytest.mark.parametrize("change", [{"quantity": "1.5"}, {"quantity": "-1"}, {"amount": "NaN"},
                                  {"amount": "-1"}, {"currency": "USD"}, {"ack": "Failure"},
                                  {"ack": "Warning"}])
def test_invalid_or_uncertain_remaining_capacity_holds(change):
    snap = parse_remaining_capacity(body(**change), observed_at=1000)
    assert not snap["complete"] and available_after_reservations(snap, now=1000) is None


def test_zero_remaining_is_zero_not_unlimited():
    snap = parse_remaining_capacity(body("0", "0.00"), observed_at=1000)
    assert snap["complete"] and available_after_reservations(snap, now=1000) == (0, D(0))


def test_missing_summary_does_not_guess():
    raw = b'<GetMyeBaySellingResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Success</Ack></GetMyeBaySellingResponse>'
    assert not parse_remaining_capacity(raw, observed_at=1000)["complete"]


@pytest.mark.parametrize("environment,host", [("production", "api.ebay.com"), ("sandbox", "api.sandbox.ebay.com")])
def test_capacity_client_can_only_make_fixed_nonmutating_call(tmp_path, monkeypatch, environment, host):
    client = ReadOnlyEbayClient(environment, tmp_path)
    monkeypatch.setattr(client, "get_user_access_token", lambda: "FAKE-TOKEN")
    def request(req, timeout):
        assert req.full_url == f"https://{host}/ws/api.dll"
        assert req.get_header("X-ebay-api-call-name") == "GetMyeBaySelling"
        assert b"<SellingSummary><Include>true</Include>" in req.data
        assert b"FAKE-TOKEN" not in req.data
        assert timeout == 30
        return io.BytesIO(body())
    monkeypatch.setattr("urllib.request.urlopen", request)
    assert client.get_remaining_selling_capacity()["complete"]
    assert client.settings.global_kill_switch and client.settings.dry_run
