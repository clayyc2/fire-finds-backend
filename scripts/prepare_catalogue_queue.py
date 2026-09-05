"""Prepare the complete catalogue queue locally; no network or publishing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from firefinds.engine.catalogue_queue import build_catalogue_queue
from firefinds.engine.storage import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--existing-mapping", required=True, type=Path)
    parser.add_argument("--purchase-audit", required=True, type=Path)
    parser.add_argument("--own-results", type=Path)
    parser.add_argument("--stock-buffer", type=int, default=2)
    parser.add_argument("--initial-quantity", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    catalogue = json.loads(args.catalogue.read_text())
    existing = json.loads(args.existing_mapping.read_text())
    audit = json.loads(args.purchase_audit.read_text())
    own = json.loads(args.own_results.read_text()) if args.own_results else {}
    denied = [r["sku"] for r in audit["rows"] if r.get("buyable") is False]
    report = build_catalogue_queue(catalogue["rows"], own_results=own, existing_skus=existing,
        purchase_denied_skus=denied, stock_buffer=args.stock_buffer, initial_quantity=args.initial_quantity)
    report["catalogue_observed_at"] = catalogue["observed_at"]
    report["own_results_supplied"] = bool(own)
    atomic_json(args.out, report)
    summary = {k:v for k,v in report.items() if k not in {"queue", "held"}}
    summary["first_ten"] = [{k:r[k] for k in ("rank", "sku", "title", "ranking_basis")} for r in report["queue"][:10]]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
