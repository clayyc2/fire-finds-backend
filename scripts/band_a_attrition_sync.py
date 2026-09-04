#!/usr/bin/env python3
"""Re-apply Band-A Browse uncompetitive_at_map attrition to live DB.

Uses freeze evidence (band_a_attrition_sync / band_a_browse_recompete) + existing
cached product economics — does NOT run live ebay-compete / Browse (that would
re-admit MAP-uncompetitive SKUs at floor).

Gates / publish / Process / $10 flat: never touched here.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path("/workspace/firefinds")
DB = ROOT / "data" / "firefinds.db"
ATTRITION_PATH = ROOT / "data" / "reports" / "band_a_attrition_sync_20260904_1348.json"
OUT_JSON = ROOT / "data" / "reports" / "band_a_attrition_sync_20260904_1348.json"
RANKED_EXPORT = ROOT / "data" / "ranked_queue.json"
MT = ZoneInfo("America/Edmonton")

# Mirror freeze: keep MAP-competitive Band-A; drop uncompetitive_at_map.
DEFAULT_KEEPS = ["HPW2020XC", "194850506413", "6100176"]
DEFAULT_DROPS = [
    "HPCF258XC",
    "HPW2022XC",
    "194850506437",
    "HPW2021XC",
    "6300406",
    "HPW2023XC",
    "6300342",
    "6300468",
    "6300489",
    "6300341",
    "6300392",
    "6300451",
]


def _now() -> tuple[str, str]:
    utc = datetime.now(timezone.utc).replace(microsecond=0)
    local = utc.astimezone(MT)
    return utc.isoformat().replace("+00:00", "+00:00"), local.strftime("%Y-%m-%d %H:%M MT")


def _counts(conn: sqlite3.Connection) -> dict:
    listable = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(listable_pass,0)=1"
    ).fetchone()[0]
    ranked = conn.execute("SELECT COUNT(*) FROM ranked_queue").fetchone()[0]
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(eligible,0)=1 "
        "AND UPPER(IFNULL(shipping_status,'')) != 'RESOLVED'"
    ).fetchone()[0]
    # Fallback: quarantine-style unresolved among scored eligible pool
    if unresolved == 0:
        unresolved = conn.execute(
            "SELECT COUNT(*) FROM products WHERE UPPER(IFNULL(shipping_status,''))='UNRESOLVED' "
            "AND IFNULL(eligible,0)=1"
        ).fetchone()[0]
    fails_expensive = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(listable_pass,0)=1 "
        "AND IFNULL(fails_expensive_destinations,0)=1"
    ).fetchone()[0]
    safe = conn.execute(
        "SELECT COUNT(*) FROM products WHERE IFNULL(listable_pass,0)=1 "
        "AND IFNULL(fails_expensive_destinations,0)=0"
    ).fetchone()[0]
    return {
        "listable": listable,
        "ranked": ranked,
        "unresolved": unresolved,
        "fails_expensive_dest": fails_expensive,
        "safe_nationwide_approx": safe,
    }


def _load_plan() -> tuple[list[str], list[str]]:
    keeps = list(DEFAULT_KEEPS)
    drops = list(DEFAULT_DROPS)
    if ATTRITION_PATH.is_file():
        data = json.loads(ATTRITION_PATH.read_text(encoding="utf-8"))
        if data.get("keeps"):
            keeps = [str(x) for x in data["keeps"]]
        if data.get("attrition"):
            drops = [str(row["sku"]) for row in data["attrition"]]
    return keeps, drops


def rebuild_ranked_queue(conn: sqlite3.Connection) -> list[dict]:
    """Rebuild ranked_queue from current listable_pass survivors (cached scores)."""
    rows = conn.execute(
        """
        SELECT sku, rank_score, expected_monthly_contribution_profit,
               sales_probability, sell_comp, listable_profit, listable_margin,
               map, stock, provisional_public_ebay, needs_official_ebay_validation,
               listable_reason, ship_p75, shipping_status,
               fails_expensive_destinations, failed_expensive_destinations
        FROM products
        WHERE IFNULL(listable_pass,0)=1
        ORDER BY IFNULL(rank_score,0) DESC,
                 IFNULL(expected_monthly_contribution_profit,0) DESC,
                 sku ASC
        """
    ).fetchall()
    cols = [
        "sku",
        "rank_score",
        "expected_monthly_contribution_profit",
        "sales_probability",
        "sell_comp",
        "listable_profit",
        "listable_margin",
        "map",
        "stock",
        "provisional_public_ebay",
        "needs_official_ebay_validation",
        "listable_reason",
        "ship_p75",
        "shipping_status",
        "fails_expensive_destinations",
        "failed_expensive_destinations",
    ]
    survivors = [dict(zip(cols, r)) for r in rows]
    conn.execute("DELETE FROM ranked_queue")
    for i, r in enumerate(survivors, start=1):
        conn.execute(
            """
            INSERT INTO ranked_queue (
                rank, sku, rank_score, expected_monthly_contribution_profit,
                sales_probability, sell_comp, listable_profit, listable_margin,
                map, stock, provisional_public_ebay,
                needs_official_ebay_validation, reason,
                ship_p75, shipping_status, fails_expensive_destinations,
                failed_expensive_destinations, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                i,
                r["sku"],
                r["rank_score"],
                r["expected_monthly_contribution_profit"],
                r["sales_probability"],
                r["sell_comp"],
                r["listable_profit"],
                r["listable_margin"],
                r["map"],
                r["stock"],
                int(r["provisional_public_ebay"] or 0),
                int(r["needs_official_ebay_validation"] if r["needs_official_ebay_validation"] is not None else 1),
                r["listable_reason"] or "ok",
                r["ship_p75"],
                r["shipping_status"],
                int(r["fails_expensive_destinations"] or 0),
                r["failed_expensive_destinations"],
            ),
        )
        conn.execute(
            "UPDATE products SET listable_rank=?, updated_at=datetime('now') WHERE sku=?",
            (i, r["sku"]),
        )
    return survivors


def main() -> int:
    if not DB.is_file():
        print(f"DB missing: {DB}", file=sys.stderr)
        return 2
    keeps, drops = _load_plan()
    drop_set = set(drops)
    keep_set = set(keeps)
    overlap = drop_set & keep_set
    if overlap:
        print(f"keeps/drops overlap: {sorted(overlap)}", file=sys.stderr)
        return 2

    utc, local = _now()
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    before = _counts(conn)

    attrition_rows = []
    for sku in drops:
        row = conn.execute(
            "SELECT sku, listable_pass FROM products WHERE sku=?", (sku,)
        ).fetchone()
        if row is None:
            print(f"WARN: attrition sku missing from products: {sku}", file=sys.stderr)
            continue
        was = int(row["listable_pass"] or 0)
        conn.execute(
            """
            UPDATE products SET
              listable=0,
              listable_pass=0,
              final_profitability=0,
              listable_rank=NULL,
              listable_reason='uncompetitive_at_map',
              rank_score=0.0,
              expected_monthly_contribution_profit=0.0,
              expected_monthly_units=0.0,
              updated_at=datetime('now')
            WHERE sku=?
            """,
            (sku,),
        )
        # Align latest ebay_competition row reason (no new Browse call)
        conn.execute(
            """
            UPDATE ebay_competition
            SET listable_pass=0, reason='uncompetitive_at_map'
            WHERE id = (
              SELECT id FROM ebay_competition WHERE sku=? ORDER BY id DESC LIMIT 1
            )
            """,
            (sku,),
        )
        attrition_rows.append(
            {"sku": sku, "reason": "uncompetitive_at_map", "was_listable": was}
        )

    # Ensure keeps remain listable (do not expand Final5/wave25; just protect Band-A keeps)
    for sku in keeps:
        row = conn.execute(
            "SELECT sku, listable_pass, shipping_status FROM products WHERE sku=?",
            (sku,),
        ).fetchone()
        if row is None:
            print(f"WARN: keep sku missing: {sku}", file=sys.stderr)
            continue
        if int(row["listable_pass"] or 0) != 1:
            print(
                f"WARN: keep {sku} not listable before sync "
                f"(listable_pass={row['listable_pass']}); leaving as-is",
                file=sys.stderr,
            )

    survivors = rebuild_ranked_queue(conn)
    after = _counts(conn)
    conn.commit()

    report = {
        "before": {
            "listable": before["listable"],
            "ranked": before["ranked"],
            "unresolved": before["unresolved"],
        },
        "after": {
            "listable": after["listable"],
            "ranked": after["ranked"],
            "unresolved": after["unresolved"],
            "fails_expensive_dest": after["fails_expensive_dest"],
            "safe_nationwide_approx": after["safe_nationwide_approx"],
        },
        "keeps": keeps,
        "attrition": attrition_rows,
        "expected_listable": 152,
        "source": "band_a_browse_attrition_sync",
        "evidence": [
            "data/reports/band_a_browse_recompete_20260904_1311.md",
            "data/reports/band_a_attrition_sync_20260904_1348.json",
        ],
        "note": (
            "No live ebay-compete / Browse. Applied uncompetitive_at_map attrition "
            "from Band-A Browse evidence; rebuilt ranked_queue from cached quotes lineage."
        ),
        "updated_at_utc": utc,
        "updated_at_mt": local,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    export = {
        "eligible_loaded": None,
        "listable_pass_count": after["listable"],
        "source": "band_a_browse_attrition_sync",
        "band_a_keeps": keeps,
        "band_a_attrition_n": len(attrition_rows),
        "top_skus": [r["sku"] for r in survivors[:25]],
        "fails_expensive_destinations_count": after["fails_expensive_dest"],
        "safe_nationwide_approx": after["safe_nationwide_approx"],
        "updated_at": utc,
    }
    RANKED_EXPORT.write_text(json.dumps(export, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    ok = (
        after["listable"] == 152
        and after["ranked"] == 152
        and after["safe_nationwide_approx"] == 127
    )
    if not ok:
        print(
            f"# MISMATCH expected listable/ranked/SAFE=152/152/127 "
            f"got {after['listable']}/{after['ranked']}/{after['safe_nationwide_approx']}",
            file=sys.stderr,
        )
        return 1
    print(
        f"# OK attrition sync: listable={after['listable']} ranked={after['ranked']} "
        f"SAFE≈{after['safe_nationwide_approx']} DEST={after['fails_expensive_dest']}",
        file=sys.stderr,
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
