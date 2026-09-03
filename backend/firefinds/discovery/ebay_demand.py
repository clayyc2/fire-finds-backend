"""EBAY_DEMAND_FIRST discovery: repeated sold demand → Randmar match → economics.

Without official eBay OAuth keys, uses provisional public sold/active signals
flagged provisional_public_ebay=true / needs_official_ebay_validation=true.
Structured so Browse / Finding / sold history APIs plug in when keys arrive.

Matching rules (controlled — no fuzzy free-for-all):
  1. Exact UPC (normalized, checksum-valid preferred)
  2. Exact MPN + manufacturer (both canonicalized)
  3. Controlled variant: exact MPN + manufacturer, optional model token equality
     when model is present on both sides (case-insensitive alnum). No edit-distance,
     no substring guessing, no brand-only matches.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.pipelines.authorize import authorize_sku
from firefinds.pipelines.cohorts import ensure_cohort_tables
from firefinds.pipelines.tags import (
    COHORT_DESTINATION_SENSITIVE,
    COHORT_QUARANTINE_UNRESOLVED,
    COHORT_SAFE_NATIONWIDE,
    PIPELINE_EBAY_DEMAND_FIRST,
    tag_candidate,
)
from firefinds.scoring.competition import evaluate_listable
from firefinds.scoring.identifiers import canonicalize_mpn, normalize_upc
from firefinds.clients.ebay import CompetitionSnapshot

_ALNUM = re.compile(r"[^A-Za-z0-9]+")


class SoldDemandProvider(Protocol):
    """Pluggable sold/active demand source (official APIs later)."""

    def discover_repeated_demand(
        self, *, marketplace_id: str = "EBAY_CA"
    ) -> list["DemandSignal"]:
        ...


@dataclass(frozen=True)
class DemandSignal:
    """One eBay CA demand observation (sold/active proxy)."""

    query: str
    query_type: str  # upc | mpn | title | category
    upc: str | None = None
    mpn: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    title: str | None = None
    sold_count: int = 0
    active_count: int = 0
    repeated_demand: bool = False
    lowest_price: float | None = None
    median_price: float | None = None
    sample_url: str | None = None
    provisional_public_ebay: bool = True
    needs_official_ebay_validation: bool = True
    source: str = "provisional_public"


@dataclass
class MatchResult:
    sku: str | None
    match_rule: str  # exact_upc | exact_mpn_manufacturer | controlled_variant | none
    product: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def _canon_mfr(raw: str | None) -> str:
    if not raw:
        return ""
    return _ALNUM.sub("", str(raw).strip().upper())


def _canon_model(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _ALNUM.sub("", str(raw).strip().upper())
    return text or None


def match_signal_to_catalog(
    signal: DemandSignal,
    products: Iterable[Mapping[str, Any]],
) -> MatchResult:
    """Apply exact UPC → exact MPN+mfr → controlled variant matching."""
    rows = [dict(p) for p in products]
    upc_norm, upc_valid = normalize_upc(signal.upc)
    if upc_norm:
        hits = []
        for r in rows:
            pu, pv = normalize_upc(r.get("upc_norm") or r.get("upc"))
            if pu and pu == upc_norm:
                hits.append(r)
        if len(hits) == 1:
            return MatchResult(
                sku=str(hits[0].get("sku")),
                match_rule="exact_upc",
                product=hits[0],
                notes=["upc_valid" if upc_valid else "upc_checksum_unverified"],
            )
        if len(hits) > 1:
            # Prefer checksum-valid catalog UPCs, then higher stock
            hits.sort(
                key=lambda r: (
                    -int(bool(r.get("upc_valid"))),
                    -int(r.get("stock") or 0),
                    str(r.get("sku") or ""),
                )
            )
            return MatchResult(
                sku=str(hits[0].get("sku")),
                match_rule="exact_upc",
                product=hits[0],
                notes=[f"upc_ambiguous_kept_best_of_{len(hits)}"],
            )

    sig_mpn = canonicalize_mpn(signal.mpn)
    sig_mfr = _canon_mfr(signal.manufacturer)
    if sig_mpn and sig_mfr:
        hits = []
        for r in rows:
            r_mpn = canonicalize_mpn(r.get("mpn_norm") or r.get("mpn"))
            r_mfr = _canon_mfr(r.get("manufacturer"))
            if r_mpn == sig_mpn and r_mfr == sig_mfr:
                hits.append(r)
        if len(hits) == 1:
            return MatchResult(
                sku=str(hits[0].get("sku")),
                match_rule="exact_mpn_manufacturer",
                product=hits[0],
            )
        if len(hits) > 1:
            # Controlled variant: require model equality when both sides have model
            sig_model = _canon_model(signal.model)
            if sig_model:
                narrowed = []
                for r in hits:
                    r_model = _canon_model(
                        r.get("model") or r.get("product_type") or r.get("title")
                    )
                    # Only accept when catalog exposes an explicit model field equal
                    # to signal model — never substring title fuzzy match.
                    cat_model = _canon_model(r.get("model"))
                    if cat_model and cat_model == sig_model:
                        narrowed.append(r)
                if len(narrowed) == 1:
                    return MatchResult(
                        sku=str(narrowed[0].get("sku")),
                        match_rule="controlled_variant",
                        product=narrowed[0],
                        notes=["model_token_equal"],
                    )
            hits.sort(
                key=lambda r: (-int(r.get("stock") or 0), str(r.get("sku") or ""))
            )
            return MatchResult(
                sku=None,
                match_rule="none",
                product=None,
                notes=[
                    "ambiguous_mpn_manufacturer",
                    f"candidates={len(hits)}",
                    "refused_without_unique_controlled_variant",
                ],
            )

    return MatchResult(sku=None, match_rule="none", product=None, notes=["no_match"])


class ProvisionalPublicDemandProvider:
    """Placeholder demand source until official eBay sold/Browse keys arrive.

    Does NOT scrape or invent sold counts. Returns an empty list by default.
    Callers may inject fixture signals for tests. When official keys exist,
    swap in OfficialEbayDemandProvider (Browse + Finding/sold).
    """

    def __init__(self, signals: list[DemandSignal] | None = None) -> None:
        self._signals = list(signals or [])

    def discover_repeated_demand(
        self, *, marketplace_id: str = "EBAY_CA"
    ) -> list[DemandSignal]:
        _ = marketplace_id
        return [
            s
            for s in self._signals
            if s.repeated_demand or s.sold_count >= 2 or s.active_count >= 3
        ]


class OfficialEbayDemandProvider:
    """Future plug-in: Browse/Finding/sold APIs once OAuth keys are present.

    Currently raises NotImplementedError so the scaffolding is explicit.
    """

    def __init__(self, ebay_client: Any) -> None:
        self.ebay = ebay_client

    def discover_repeated_demand(
        self, *, marketplace_id: str = "EBAY_CA"
    ) -> list[DemandSignal]:
        raise NotImplementedError(
            "OfficialEbayDemandProvider requires Browse/Finding/sold API wiring "
            f"for {marketplace_id}; use ProvisionalPublicDemandProvider until keys arrive."
        )


MATCH_RULES_DOC = """
EBAY_DEMAND_FIRST ↔ Randmar catalog match rules
==============================================
1) exact_upc
   - Normalize both sides (digit strip, optional zero-pad).
   - Prefer checksum-valid UPCs; single hit wins; multi-hit keeps best stock.

2) exact_mpn_manufacturer
   - canonicalize_mpn (upper, strip spaces/punct) AND manufacturer alnum-upper.
   - Both must be present and equal. Single hit required to accept without model.

3) controlled_variant
   - Only when exact MPN+manufacturer yields multiple catalog rows.
   - Accept iff signal.model and product.model both present and alnum-equal.
   - No edit distance, no token subset, no title substring, no brand-only.

Anything else → no_match (not linked).
"""


def _cohort_for_product(product: Mapping[str, Any], *, finally_ok: bool) -> str:
    if str(product.get("shipping_status") or "").upper() != "RESOLVED":
        return COHORT_QUARANTINE_UNRESOLVED
    if not finally_ok:
        return COHORT_QUARANTINE_UNRESOLVED
    if int(product.get("fails_expensive_destinations") or 0):
        return COHORT_DESTINATION_SENSITIVE
    return COHORT_SAFE_NATIONWIDE


def discover_ebay_demand_first(
    *,
    settings: Settings | None = None,
    snapshot_id: str,
    demand_provider: SoldDemandProvider | None = None,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    """Run EBAY_DEMAND_FIRST: demand → match → economics → authorize → rank.

    No arbitrary candidate caps. Soft respect EBAY_SELLING_LIMIT for export
    metadata only (does not drop ranked candidates from persistence).
    """
    settings = settings or get_settings()
    data_dir = Path(settings.db_path).parent
    out_dir = Path(
        export_dir or (data_dir / "cohorts" / snapshot_id / "ebay_demand_first")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "MATCH_RULES.md").write_text(MATCH_RULES_DOC.strip() + "\n", encoding="utf-8")

    provider: SoldDemandProvider = demand_provider or ProvisionalPublicDemandProvider()
    signals = provider.discover_repeated_demand(
        marketplace_id=settings.ebay_marketplace_id
    )

    conn = init_db(settings.db_path)
    ensure_cohort_tables(conn)
    catalog = [dict(r) for r in conn.execute("SELECT * FROM products").fetchall()]

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []

    for signal in signals:
        m = match_signal_to_catalog(signal, catalog)
        sig_dict = {
            "query": signal.query,
            "query_type": signal.query_type,
            "upc": signal.upc,
            "mpn": signal.mpn,
            "manufacturer": signal.manufacturer,
            "model": signal.model,
            "sold_count": signal.sold_count,
            "active_count": signal.active_count,
            "repeated_demand": signal.repeated_demand,
            "provisional_public_ebay": signal.provisional_public_ebay,
            "needs_official_ebay_validation": signal.needs_official_ebay_validation,
            "source": signal.source,
            "match_rule": m.match_rule,
            "match_notes": m.notes,
        }
        if not m.sku or not m.product:
            unmatched.append(sig_dict)
            continue

        product = dict(m.product)
        snap = CompetitionSnapshot(
            query=signal.query,
            query_type=signal.query_type,
            item_count=max(signal.sold_count, signal.active_count, 1),
            lowest_price=signal.lowest_price,
            median_price=signal.median_price or signal.lowest_price,
            sample_url=signal.sample_url,
        )
        ship_status = str(product.get("shipping_status") or "UNRESOLVED")
        ship_cost = product.get("ship_p75")
        if ship_cost is None:
            ship_cost = product.get("ship_est")
        eval_res = evaluate_listable(
            product,
            snap,
            settings,
            provisional_public_ebay=True,
            needs_official_ebay_validation=True,
            shipping_status=ship_status,
            shipping_cost_cad=float(ship_cost) if ship_cost is not None else None,
        )
        auth = authorize_sku(
            {
                **product,
                "sell_comp": eval_res.sell_comp,
                "opportunity_only": product.get("opportunity_only"),
            }
        )
        finally_ok = bool(eval_res.final_profitability and auth["map_ok"] and auth["channel_ok"])
        cohort = _cohort_for_product(product, finally_ok=finally_ok)
        # Destination-sensitive still sellable; quarantine is not.
        sellable = cohort in {
            COHORT_SAFE_NATIONWIDE,
            COHORT_DESTINATION_SENSITIVE,
        } and bool(eval_res.final_profitability and auth["map_ok"])
        if auth["opportunity_only"]:
            sellable = False
            cohort = COHORT_QUARANTINE_UNRESOLVED

        row = tag_candidate(
            {
                **product,
                "sell_comp": eval_res.sell_comp,
                "listable_profit": eval_res.contribution_profit,
                "listable_margin": eval_res.contribution_margin,
                "listable_pass": 1 if sellable else 0,
                "listable_reason": eval_res.reason,
                "rank_score": eval_res.rank_score,
                "expected_monthly_contribution_profit": (
                    eval_res.expected_monthly_contribution_profit
                ),
                "sales_probability": eval_res.sales_probability,
                "shipping_status": eval_res.shipping_status,
                "ship_p75": ship_cost,
                "fails_expensive_destinations": int(
                    product.get("fails_expensive_destinations") or 0
                ),
                "provisional_public_ebay": True,
                "needs_official_ebay_validation": True,
                "match_rule": m.match_rule,
                "demand": sig_dict,
                "authorization": auth,
                "map_ok": auth["map_ok"],
                "channel_ok": auth["channel_ok"],
                "needs_manual_channel_review": auth["needs_manual_channel_review"],
            },
            pipeline_source=PIPELINE_EBAY_DEMAND_FIRST,
            cohort=cohort,
            snapshot_id=snapshot_id,
        )
        matched.append(row)
        if sellable:
            survivors.append(row)

    survivors.sort(
        key=lambda r: (
            -float(r.get("rank_score") or 0),
            -int((r.get("demand") or {}).get("sold_count") or 0),
            str(r.get("sku") or ""),
        )
    )
    for i, r in enumerate(survivors, start=1):
        r["rank"] = i

    # Persist sellable + quarantine matched into candidate_cohorts
    conn.execute(
        "DELETE FROM candidate_cohorts WHERE pipeline_source=? AND snapshot_id=?",
        (PIPELINE_EBAY_DEMAND_FIRST, snapshot_id),
    )
    for row in matched:
        conn.execute(
            """
            INSERT INTO candidate_cohorts (
                sku, pipeline_source, cohort, comparison_cohort_id, snapshot_id,
                rank, fails_expensive_destinations, listable_profit, listable_margin,
                sell_comp, map, ship_p75, shipping_status,
                sell_through, time_to_first_sale, contribution_profit_realized,
                cancellations, returns, detail_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                row.get("sku"),
                PIPELINE_EBAY_DEMAND_FIRST,
                row.get("cohort"),
                row.get("comparison_cohort_id"),
                snapshot_id,
                row.get("rank"),
                int(row.get("fails_expensive_destinations") or 0),
                row.get("listable_profit"),
                row.get("listable_margin"),
                row.get("sell_comp"),
                row.get("map"),
                row.get("ship_p75"),
                row.get("shipping_status"),
                row.get("sell_through"),
                row.get("time_to_first_sale"),
                row.get("contribution_profit_realized"),
                row.get("cancellations"),
                row.get("returns"),
                json.dumps(row, default=str),
            ),
        )
    conn.commit()

    selling_limit = int(getattr(settings, "ebay_selling_limit", 0) or 0)
    export_survivors = survivors
    truncated_for_limit = False
    if selling_limit > 0 and len(survivors) > selling_limit:
        # Soft display/export note only — full list still in ranked export file
        truncated_for_limit = True

    summary = {
        "pipeline_source": PIPELINE_EBAY_DEMAND_FIRST,
        "snapshot_id": snapshot_id,
        "status": (
            "scaffolded_no_live_matches"
            if not signals
            else ("live_matches" if survivors else "signals_no_sellable_matches")
        ),
        "signals_seen": len(signals),
        "matched_catalog": len(matched),
        "unmatched_signals": len(unmatched),
        "sellable_survivors": len(survivors),
        "safe_nationwide": sum(
            1 for r in survivors if r.get("cohort") == COHORT_SAFE_NATIONWIDE
        ),
        "destination_sensitive": sum(
            1 for r in survivors if r.get("cohort") == COHORT_DESTINATION_SENSITIVE
        ),
        "ebay_selling_limit": selling_limit,
        "export_truncated_for_limit_note_only": truncated_for_limit,
        "provisional_public_ebay": True,
        "needs_official_ebay_validation": True,
        "match_rules_path": str(out_dir / "MATCH_RULES.md"),
        "export_dir": str(out_dir),
    }

    payload = {
        "summary": summary,
        "survivors": export_survivors,
        "matched": matched,
        "unmatched": unmatched,
    }
    (out_dir / "ebay_demand_first_ranked.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    conn.close()
    return payload
