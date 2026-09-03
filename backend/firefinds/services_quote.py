"""Checkpointed multi-destination Randmar shipping quotes.

Read-only Cart/ShippingMethods + ShippingLabel/Estimate. Never Process/orders.
Profitability shipping cost = 75th percentile of resolved representative dests.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.scoring.shipping import (
    FULFILLMENT_NOTE,
    InjectedQuoteProvider,
    MultiDestQuote,
    REPRESENTATIVE_DESTINATIONS,
    RandmarQuoteProvider,
    ShippingQuoteProvider,
    aggregate_destination_quotes,
    quote_representative_destinations,
)

PROGRESS_NAME = "shipping_quote_progress.json"
QUOTES_EXPORT_NAME = "shipping_quotes.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _progress_path(settings: Settings) -> Path:
    return settings.db_path.parent / PROGRESS_NAME


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def persist_destination_quotes(
    conn,
    sku: str,
    bundle: MultiDestQuote,
) -> None:
    for dq in bundle.quotes:
        dest = dq.destination
        q = dq.quote
        conn.execute(
            """
            INSERT INTO shipping_quotes (
                sku, dest_id, city, province, postal_code, cost_cad, status,
                warehouse, carrier, method_id, source, quoted_at, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sku, dest_id) DO UPDATE SET
                city=excluded.city,
                province=excluded.province,
                postal_code=excluded.postal_code,
                cost_cad=excluded.cost_cad,
                status=excluded.status,
                warehouse=excluded.warehouse,
                carrier=excluded.carrier,
                method_id=excluded.method_id,
                source=excluded.source,
                quoted_at=excluded.quoted_at,
                detail_json=excluded.detail_json
            """,
            (
                sku,
                dest.dest_id,
                dest.city,
                dest.province,
                dest.postal_code,
                q.cost_cad,
                q.status,
                q.warehouse,
                q.carrier,
                q.method_id,
                q.source,
                _utc_now(),
                json.dumps(q.detail, default=str),
            ),
        )
    dest_snapshot = {
        "p75_cad": bundle.p75_cad,
        "status": bundle.status,
        "resolved_n": bundle.resolved_n,
        "unresolved_n": bundle.unresolved_n,
        "dest_costs": bundle.dest_costs,
        "fulfillment_note": FULFILLMENT_NOTE,
        "quotes": [
            {
                "dest_id": dq.destination.dest_id,
                "city": dq.destination.city,
                "province": dq.destination.province,
                "postal_code": dq.destination.postal_code,
                "status": dq.quote.status,
                "cost_cad": dq.quote.cost_cad,
                "source": dq.quote.source,
                "carrier": dq.quote.carrier,
            }
            for dq in bundle.quotes
        ],
    }
    conn.execute(
        """
        UPDATE products SET
            ship_est=?,
            ship_p75=?,
            ship_quote_n=?,
            shipping_status=?,
            dest_quotes_json=?,
            ship_model=?,
            updated_at=datetime('now')
        WHERE sku=?
        """,
        (
            bundle.shipping_cost_cad,
            bundle.p75_cad,
            bundle.resolved_n,
            bundle.status,
            json.dumps(dest_snapshot, default=str),
            "multi_dest_p75",
            sku,
        ),
    )


def load_cached_bundle(conn, sku: str) -> MultiDestQuote | None:
    dests = {d.dest_id: d for d in REPRESENTATIVE_DESTINATIONS}
    rows = conn.execute(
        "SELECT * FROM shipping_quotes WHERE sku=?", (sku,)
    ).fetchall()
    if not rows:
        return None
    from firefinds.scoring.shipping import DestinationQuote, ShippingQuote

    quotes = []
    seen = set()
    for row in rows:
        dest = dests.get(str(row["dest_id"]))
        if dest is None:
            continue
        seen.add(dest.dest_id)
        status = str(row["status"] or "UNRESOLVED")
        cost = row["cost_cad"]
        if status == "RESOLVED" and cost is not None:
            q = ShippingQuote(
                status="RESOLVED",
                cost_cad=float(cost),
                warehouse=row["warehouse"],
                carrier=row["carrier"],
                method_id=row["method_id"],
                source=row["source"] or "cached",
            )
        else:
            q = ShippingQuote.unresolved(
                reason="cached_unresolved",
                warehouse=row["warehouse"],
                source=row["source"] or "cached",
            )
        quotes.append(DestinationQuote(destination=dest, quote=q))
    if len(seen) < len(dests):
        return None  # incomplete — caller should re-quote
    return aggregate_destination_quotes(quotes)


def sku_quote_complete(conn, sku: str) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) FROM shipping_quotes WHERE sku=?", (sku,)
    ).fetchone()[0]
    return int(n) >= len(REPRESENTATIVE_DESTINATIONS)


def default_quote_provider(settings: Settings) -> ShippingQuoteProvider:
    if settings.ship_quote_enabled:
        try:
            from firefinds.clients.randmar import RandmarClient

            return RandmarQuoteProvider(RandmarClient(settings))
        except Exception:  # noqa: BLE001
            return InjectedQuoteProvider()
    return InjectedQuoteProvider()


def quote_eligible_skus(
    *,
    settings: Settings | None = None,
    quote_provider: ShippingQuoteProvider | None = None,
    limit: int | None = None,
    sleep_sec: float | None = None,
    resume: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Quote representative dests for eligible/score_pass SKUs with checkpoint."""
    settings = settings or get_settings()
    sleep = (
        float(sleep_sec)
        if sleep_sec is not None
        else float(settings.ship_quote_sleep_sec)
    )
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    provider = quote_provider or default_quote_provider(settings)

    sql = """
        SELECT * FROM products
        WHERE IFNULL(eligible, 0) = 1
           OR (score_pass = 1 AND IFNULL(paused, 0) = 0)
        ORDER BY IFNULL(score, 0) DESC, sku ASC
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in conn.execute(sql).fetchall()]

    progress_path = _progress_path(settings)
    quoted = 0
    skipped = 0
    resolved_skus = 0
    unresolved_skus = 0
    dest_resolved = 0
    dest_unresolved = 0
    last_sku = None

    logger.log(
        "quote_shipping",
        decision="start",
        detail={
            "eligible_loaded": len(rows),
            "limit": limit,
            "resume": resume,
            "force": force,
            "sleep_sec": sleep,
            "destinations": [d.dest_id for d in REPRESENTATIVE_DESTINATIONS],
            "fulfillment_note": FULFILLMENT_NOTE,
        },
        source="quote-shipping",
    )

    for row in rows:
        sku = str(row.get("sku") or "")
        last_sku = sku
        if not sku:
            continue
        if resume and not force and sku_quote_complete(conn, sku):
            cached = load_cached_bundle(conn, sku)
            skipped += 1
            if cached and cached.resolved:
                resolved_skus += 1
            else:
                unresolved_skus += 1
            if cached:
                dest_resolved += cached.resolved_n
                dest_unresolved += cached.unresolved_n
            continue

        bundle = quote_representative_destinations(
            provider, row, sleep_sec=sleep
        )
        persist_destination_quotes(conn, sku, bundle)
        conn.commit()
        quoted += 1
        dest_resolved += bundle.resolved_n
        dest_unresolved += bundle.unresolved_n
        if bundle.resolved:
            resolved_skus += 1
        else:
            unresolved_skus += 1
        logger.log(
            "shipping_quote_multi",
            sku=sku,
            decision=bundle.status,
            detail={
                "p75_cad": bundle.p75_cad,
                "resolved_n": bundle.resolved_n,
                "dest_costs": bundle.dest_costs,
            },
            source="quote-shipping",
        )
        _write_json(
            progress_path,
            {
                "updated_at": _utc_now(),
                "eligible_loaded": len(rows),
                "quoted": quoted,
                "skipped_cached": skipped,
                "resolved_skus": resolved_skus,
                "unresolved_skus": unresolved_skus,
                "dest_resolved": dest_resolved,
                "dest_unresolved": dest_unresolved,
                "last_sku": last_sku,
                "limit": limit,
                "sleep_sec": sleep,
                "fulfillment_note": FULFILLMENT_NOTE,
                "destinations": [
                    {
                        "dest_id": d.dest_id,
                        "city": d.city,
                        "province": d.province,
                        "postal_code": d.postal_code,
                    }
                    for d in REPRESENTATIVE_DESTINATIONS
                ],
            },
        )

    summary = {
        "eligible_loaded": len(rows),
        "quoted": quoted,
        "skipped_cached": skipped,
        "resolved_skus": resolved_skus,
        "unresolved_skus": unresolved_skus,
        "dest_resolved": dest_resolved,
        "dest_unresolved": dest_unresolved,
        "progress_path": str(progress_path),
        "fulfillment_note": FULFILLMENT_NOTE,
    }
    # Export snapshot of quotes table
    export_path = settings.db_path.parent / QUOTES_EXPORT_NAME
    export_rows = [dict(r) for r in conn.execute("SELECT * FROM shipping_quotes").fetchall()]
    _write_json(
        export_path,
        {
            "summary": summary,
            "fulfillment_note": FULFILLMENT_NOTE,
            "quotes": export_rows,
        },
    )
    summary["export_path"] = str(export_path)
    _write_json(progress_path, {**summary, "updated_at": _utc_now(), "complete": True})
    logger.log(
        "quote_shipping",
        decision="complete",
        detail=summary,
        source="quote-shipping",
    )
    logger.close()
    return summary


def load_sku_dest_costs(conn, sku: str) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT dest_id, cost_cad FROM shipping_quotes
        WHERE sku=? AND status='RESOLVED' AND cost_cad IS NOT NULL
        """,
        (sku,),
    ).fetchall()
    return {str(r["dest_id"]): float(r["cost_cad"]) for r in rows}


class CachedQuoteProvider:
    """Serve previously persisted dest quotes; optional live fallback."""

    def __init__(
        self,
        conn,
        fallback: ShippingQuoteProvider | None = None,
    ) -> None:
        self.conn = conn
        self.fallback = fallback

    def quote_product(
        self,
        product: Mapping[str, Any],
        *,
        ship_to: Mapping[str, str],
    ):
        from firefinds.scoring.shipping import ShippingQuote

        sku = str(product.get("sku") or "")
        dest_id = str(ship_to.get("dest_id") or "")
        postal = str(ship_to.get("PostalCode") or "")
        row = None
        if dest_id:
            row = self.conn.execute(
                "SELECT * FROM shipping_quotes WHERE sku=? AND dest_id=?",
                (sku, dest_id),
            ).fetchone()
        if row is None and postal:
            row = self.conn.execute(
                "SELECT * FROM shipping_quotes WHERE sku=? AND postal_code=?",
                (sku, postal),
            ).fetchone()
        if row is not None:
            if row["status"] == "RESOLVED" and row["cost_cad"] is not None:
                return ShippingQuote(
                    status="RESOLVED",
                    cost_cad=float(row["cost_cad"]),
                    warehouse=row["warehouse"],
                    carrier=row["carrier"],
                    method_id=row["method_id"],
                    source="cached",
                )
            return ShippingQuote.unresolved(
                reason="cached_unresolved",
                source="cached",
            )
        if self.fallback is not None:
            return self.fallback.quote_product(product, ship_to=ship_to)
        return ShippingQuote.unresolved(reason="no_cached_quote", source="cached")

    def quote_destinations(self, product, destinations, *, sleep_sec: float = 0.0):
        from firefinds.scoring.shipping import DestinationQuote

        _ = sleep_sec
        sku = str(product.get("sku") or "")
        cached = load_cached_bundle(self.conn, sku)
        if cached is not None:
            return list(cached.quotes)
        if self.fallback is not None and hasattr(self.fallback, "quote_destinations"):
            return self.fallback.quote_destinations(
                product, destinations, sleep_sec=sleep_sec
            )
        out = []
        for dest in destinations:
            ship_to = {
                "dest_id": dest.dest_id,
                "PostalCode": dest.postal_code,
            }
            out.append(
                DestinationQuote(
                    destination=dest,
                    quote=self.quote_product(product, ship_to=ship_to),
                )
            )
        return out
