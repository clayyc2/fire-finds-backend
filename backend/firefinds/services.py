"""Ingest / score / rank service helpers used by the CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from firefinds.action_log.logger import ActionLogger
from firefinds.config import Settings, get_settings
from firefinds.db.schema import init_db
from firefinds.scoring.filters import ScoreThresholds, score_product

# Deterministic stub catalog for offline ingest (no live API / no secrets).
STUB_PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "FF-STUB-001",
        "upc": "000111222333",
        "mpn": "STUB-A1",
        "manufacturer": "Acme",
        "map": 49.99,
        "msrp": 59.99,
        "dealer_cost": 30.00,
        "rebate": 0.0,
        "stock": 10,
        "landed_cost": 32.00,
    },
    {
        "sku": "FF-STUB-002",
        "upc": "000111222334",
        "mpn": "STUB-B2",
        "manufacturer": "Acme",
        "map": 19.99,
        "msrp": 24.99,
        "dealer_cost": 16.00,
        "rebate": 0.0,
        "stock": 5,
        "landed_cost": 16.50,
    },
    {
        "sku": "FF-STUB-003",
        "upc": "000111222335",
        "mpn": "STUB-C3",
        "manufacturer": "BetaCo",
        "map": 99.00,
        "msrp": 120.00,
        "dealer_cost": 70.00,
        "rebate": 5.0,
        "stock": 1,
        "landed_cost": 72.00,
    },
    {
        "sku": "FF-STUB-004",
        "upc": "000111222336",
        "mpn": "STUB-D4",
        "manufacturer": "BetaCo",
        "map": 80.00,
        "msrp": 90.00,
        "dealer_cost": 50.00,
        "rebate": 0.0,
        "stock": 20,
        "landed_cost": 52.00,
    },
    {
        "sku": "FF-STUB-005",
        "upc": None,
        "mpn": "STUB-E5",
        "manufacturer": "Gamma",
        "map": 0,
        "msrp": 0,
        "dealer_cost": 10.00,
        "rebate": 0.0,
        "stock": 50,
        "landed_cost": 10.00,
    },
]


UPSERT_SQL = """
INSERT INTO products (
    sku, upc, mpn, manufacturer, map, msrp, dealer_cost, rebate, stock,
    landed_cost, contribution_profit, contribution_margin, score,
    score_pass, score_reason, paused, pause_reason, scored_at, updated_at
) VALUES (
    :sku, :upc, :mpn, :manufacturer, :map, :msrp, :dealer_cost, :rebate, :stock,
    :landed_cost, :contribution_profit, :contribution_margin, :score,
    :score_pass, :score_reason, :paused, :pause_reason, datetime('now'), datetime('now')
)
ON CONFLICT(sku) DO UPDATE SET
    upc=excluded.upc,
    mpn=excluded.mpn,
    manufacturer=excluded.manufacturer,
    map=excluded.map,
    msrp=excluded.msrp,
    dealer_cost=excluded.dealer_cost,
    rebate=excluded.rebate,
    stock=excluded.stock,
    landed_cost=excluded.landed_cost,
    contribution_profit=excluded.contribution_profit,
    contribution_margin=excluded.contribution_margin,
    score=excluded.score,
    score_pass=excluded.score_pass,
    score_reason=excluded.score_reason,
    paused=excluded.paused,
    pause_reason=excluded.pause_reason,
    scored_at=excluded.scored_at,
    updated_at=datetime('now');
"""


def _thresholds(settings: Settings) -> ScoreThresholds:
    return ScoreThresholds(
        min_contribution_profit_cad=settings.min_contribution_profit_cad,
        min_contribution_margin=settings.min_contribution_margin,
        stock_buffer=settings.stock_buffer,
    )


def _row_from_product(
    product: Mapping[str, Any],
    result,
    *,
    paused: int = 0,
    pause_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "sku": product["sku"],
        "upc": product.get("upc"),
        "mpn": product.get("mpn"),
        "manufacturer": product.get("manufacturer"),
        "map": product.get("map"),
        "msrp": product.get("msrp"),
        "dealer_cost": product.get("dealer_cost"),
        "rebate": product.get("rebate") or 0,
        "stock": product.get("stock") or 0,
        "landed_cost": product.get("landed_cost"),
        "contribution_profit": result.contribution_profit,
        "contribution_margin": result.contribution_margin,
        "score": result.score,
        "score_pass": 1 if result.passed else 0,
        "score_reason": result.reason,
        "paused": paused,
        "pause_reason": pause_reason,
    }


def ingest_products(
    products: Iterable[Mapping[str, Any]],
    *,
    settings: Settings | None = None,
    score: bool = True,
    source: str = "ingest",
) -> int:
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    th = _thresholds(settings)
    count = 0
    for product in products:
        sku = str(product["sku"])
        if score:
            result = score_product(product, th)
            row = _row_from_product(product, result)
            decision = "pass" if result.passed else "reject"
            logger.log(
                "score",
                sku=sku,
                decision=decision,
                detail={
                    "profit": result.contribution_profit,
                    "margin": result.contribution_margin,
                    "score": result.score,
                    "reasons": list(result.reasons),
                },
                source=source,
            )
        else:
            # Store raw with null scored fields
            class _Empty:
                contribution_profit = None
                contribution_margin = None
                score = None
                passed = False
                reason = "unscored"

            row = _row_from_product(product, _Empty())
            row["score_pass"] = 0

        conn.execute(UPSERT_SQL, row)
        logger.log(
            "ingest",
            sku=sku,
            decision="upserted",
            detail={"source": source},
            source=source,
        )
        count += 1
    conn.commit()
    logger.close()
    return count


def ingest_stub(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return ingest_products(STUB_PRODUCTS, settings=settings, source="ingest-stub")


def score_all(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    th = _thresholds(settings)
    rows = conn.execute(
        "SELECT sku, upc, mpn, manufacturer, map, msrp, dealer_cost, rebate, "
        "stock, landed_cost, paused FROM products"
    ).fetchall()
    updated = 0
    for row in rows:
        product = dict(row)
        if product.get("paused"):
            logger.log(
                "score",
                sku=product["sku"],
                decision="skipped_paused",
                detail={},
                source="score",
            )
            continue
        result = score_product(product, th)
        conn.execute(
            """
            UPDATE products SET
                contribution_profit=?,
                contribution_margin=?,
                score=?,
                score_pass=?,
                score_reason=?,
                scored_at=datetime('now'),
                updated_at=datetime('now')
            WHERE sku=?
            """,
            (
                result.contribution_profit,
                result.contribution_margin,
                result.score,
                1 if result.passed else 0,
                result.reason,
                product["sku"],
            ),
        )
        logger.log(
            "score",
            sku=product["sku"],
            decision="pass" if result.passed else "reject",
            detail={
                "profit": result.contribution_profit,
                "margin": result.contribution_margin,
                "score": result.score,
                "reasons": list(result.reasons),
            },
            source="score",
        )
        updated += 1
    conn.commit()
    logger.close()
    return updated


def rank_candidates(
    n: int = 10,
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    conn = init_db(settings.db_path)
    logger = ActionLogger(settings.actions_jsonl, conn=conn)
    rows = conn.execute(
        """
        SELECT sku, manufacturer, map, msrp, stock, landed_cost,
               contribution_profit, contribution_margin, score, score_reason
        FROM products
        WHERE score_pass = 1 AND paused = 0
        ORDER BY score DESC, sku ASC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    results = [dict(r) for r in rows]
    logger.log(
        "rank",
        decision="top_n",
        detail={"n": n, "returned": len(results), "skus": [r["sku"] for r in results]},
        source="rank",
    )
    logger.close()
    return results
