"""Collapse duplicate UPC or same MPN+manufacturer variants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class DedupeMerge:
    kept_sku: str
    dropped_sku: str
    key: str
    reason: str


def _profit(row: Mapping[str, Any]) -> float:
    try:
        return float(row.get("contribution_profit") or row.get("listable_profit") or 0)
    except (TypeError, ValueError):
        return 0.0


def _stock(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("stock") or 0)
    except (TypeError, ValueError):
        return 0


def _better(a: Mapping[str, Any], b: Mapping[str, Any]) -> Mapping[str, Any]:
    """Prefer higher stock, then higher profit, then lexicographically smaller sku."""
    sa, sb = _stock(a), _stock(b)
    if sa != sb:
        return a if sa > sb else b
    pa, pb = _profit(a), _profit(b)
    if pa != pb:
        return a if pa > pb else b
    ska, skb = str(a.get("sku") or ""), str(b.get("sku") or "")
    return a if ska <= skb else b


def dedupe_products(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[DedupeMerge]]:
    """Keep best row per normalized UPC, else per mpn_norm+manufacturer."""
    by_upc: dict[str, dict[str, Any]] = {}
    by_mpn: dict[str, dict[str, Any]] = {}
    merges: list[DedupeMerge] = []
    no_key: list[dict[str, Any]] = []

    for raw in rows:
        row = dict(raw)
        sku = str(row.get("sku") or "")
        upc = (row.get("upc_norm") or row.get("upc") or "")
        upc = str(upc).strip()
        mpn = (row.get("mpn_norm") or row.get("mpn") or "")
        mpn = str(mpn).strip().upper()
        mfr = str(row.get("manufacturer") or "").strip().upper()

        if upc:
            key = f"upc:{upc}"
            prev = by_upc.get(upc)
            if prev is None:
                by_upc[upc] = row
            else:
                winner = _better(prev, row)
                loser = row if winner is prev else prev
                by_upc[upc] = dict(winner)
                merges.append(
                    DedupeMerge(
                        kept_sku=str(winner.get("sku")),
                        dropped_sku=str(loser.get("sku")),
                        key=key,
                        reason="duplicate_upc",
                    )
                )
            continue

        if mpn and mfr:
            mk = f"{mfr}::{mpn}"
            key = f"mpn:{mk}"
            prev = by_mpn.get(mk)
            if prev is None:
                by_mpn[mk] = row
            else:
                winner = _better(prev, row)
                loser = row if winner is prev else prev
                by_mpn[mk] = dict(winner)
                merges.append(
                    DedupeMerge(
                        kept_sku=str(winner.get("sku")),
                        dropped_sku=str(loser.get("sku")),
                        key=key,
                        reason="duplicate_mpn_mfr",
                    )
                )
            continue

        no_key.append(row)

    # Drop mpn-group rows that share UPC already kept
    kept_upcs = set(by_upc.keys())
    mpn_kept: list[dict[str, Any]] = []
    for row in by_mpn.values():
        u = str(row.get("upc_norm") or row.get("upc") or "").strip()
        if u and u in kept_upcs and str(row.get("sku")) != str(by_upc[u].get("sku")):
            merges.append(
                DedupeMerge(
                    kept_sku=str(by_upc[u].get("sku")),
                    dropped_sku=str(row.get("sku")),
                    key=f"upc:{u}",
                    reason="mpn_shadowed_by_upc",
                )
            )
            continue
        mpn_kept.append(row)

    out = list(by_upc.values()) + mpn_kept + no_key
    return out, merges
