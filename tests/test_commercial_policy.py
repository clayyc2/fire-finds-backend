from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from decimal import Decimal as D
import json
from zoneinfo import ZoneInfo

import pytest

from firefinds.config import Settings
from firefinds.engine.models import Candidate
from firefinds.engine.services import OpportunityEngine
from firefinds.fulfillment.spend_budget import DailySupplierBudget


def candidate(**changes):
    return replace(Candidate("SKU", D(20), D(10), 10, map_price=D(0), channel_allowed=True), **changes)


def test_price_keeps_upside_instead_of_selling_at_minimum():
    decision = OpportunityEngine(Settings(market_research_enabled=True)).evaluate(candidate(competitor_price=D(100)))
    assert decision.allowed and decision.price == D("99.99")
    assert decision.margin > D(".18") and decision.profit > 8


def test_price_exceeds_cheap_competitor_when_needed_for_floor():
    decision = OpportunityEngine(Settings(market_research_enabled=True)).evaluate(candidate(competitor_price=D(25)))
    assert decision.allowed and decision.reason == "FLOOR_ABOVE_COMPETITION"
    assert decision.price > 25 and decision.margin >= D(".18") and decision.profit >= 8


def test_map_and_configurable_undercut_preserve_minimums():
    engine = OpportunityEngine(Settings(competitor_undercut_cad=.10, market_research_enabled=True))
    assert engine.evaluate(candidate(competitor_price=D(100))).price == D("99.90")
    assert engine.evaluate(candidate(competitor_price=D(100), map_price=D(120))).price == D(120)


def budget(tmp_path, clock=None, **settings):
    return DailySupplierBudget(Settings(**settings), tmp_path / "spend.json", clock or (lambda: 1000))


def test_exact_cap_rejects_next_cent_without_running_operation(tmp_path):
    guard = budget(tmp_path)
    calls = []
    assert guard.execute("A", D(2000), lambda: calls.append("A"))["allowed"]
    assert guard.execute("B", D(500), lambda: calls.append("B"))["allowed"]
    assert not guard.execute("C", D(".01"), lambda: calls.append("C"))["allowed"]
    assert calls == ["A", "B"]
    assert (tmp_path / "spend.json").stat().st_mode & 0o077 == 0


def test_concurrent_authorizations_cannot_overbook_cash(tmp_path):
    def buy(i):
        return budget(tmp_path).execute(str(i), D(1500), lambda: "confirmed")
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(buy, range(4)))
    assert sum(r["allowed"] for r in outcomes) == 1


def test_restart_does_not_reset_spending_or_allow_replay(tmp_path):
    assert budget(tmp_path).execute("A", D(2500), lambda: "confirmed")["allowed"]
    assert not budget(tmp_path).execute("B", D(1), lambda: pytest.fail("must not call"))["allowed"]
    assert not budget(tmp_path).execute("A", D(1), lambda: pytest.fail("must not replay"))["allowed"]


def test_day_boundary_is_edmonton_midnight_and_uncertainty_carries_forward(tmp_path):
    def stamp(day, hour, minute=0):
        return datetime(2026, 9, day, hour, minute, tzinfo=ZoneInfo("America/Edmonton")).timestamp()
    now = [stamp(5, 23, 59)]
    guard = budget(tmp_path, clock=lambda: now[0])
    guard.execute("spent", D(1000), lambda: "done")
    def timeout():
        raise TimeoutError()
    with pytest.raises(TimeoutError):
        guard.execute("uncertain", D(1500), timeout)
    now[0] = stamp(6, 0)
    assert not guard.execute("too-much", D(1001), lambda: None)["allowed"]
    assert guard.execute("fits", D(1000), lambda: "done")["allowed"]
    guard.confirm("uncertain")
    assert not guard.execute("still-full", D(1), lambda: None)["allowed"]
    now[0] = stamp(7, 0)
    assert guard.execute("tomorrow", D(2500), lambda: "done")["allowed"]


def test_request_crossing_midnight_conservatively_counts_both_days(tmp_path):
    now = [datetime(2026, 9, 5, 23, 59, tzinfo=ZoneInfo("America/Edmonton")).timestamp()]
    guard = budget(tmp_path, clock=lambda: now[0])
    def crosses_midnight():
        now[0] += 120
    assert guard.execute("A", D(2500), crosses_midnight)["allowed"]
    assert not guard.execute("B", D(1), lambda: None)["allowed"]


@pytest.mark.parametrize("amount", [0, -1, "NaN", "Infinity"])
def test_invalid_reservations_fail_closed(tmp_path, amount):
    with pytest.raises(ValueError):
        budget(tmp_path).execute("A", amount, lambda: pytest.fail("must not call"))


def test_corrupt_spend_state_is_not_discarded(tmp_path):
    (tmp_path / "spend.json").write_text('{"A":{"state":"SPENT"}}')
    with pytest.raises(ValueError):
        budget(tmp_path).execute("A", D(1), lambda: pytest.fail("must not call"))


def test_rounded_up_cash_reservation_cannot_exceed_cap(tmp_path):
    assert not budget(tmp_path).execute("A", D("2500.001"), lambda: pytest.fail("must not call"))["allowed"]
