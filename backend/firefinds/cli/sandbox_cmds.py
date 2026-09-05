"""CLI helpers for sandbox reads, ingest dry-run, and simulated E2E."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from firefinds.clients.ebay import EbayClient
from firefinds.config import get_settings
from firefinds.engine.sandbox_ops import fixture_lifecycle, sanitized_read_report


def cmd_ebay_sandbox_reads(_args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.ebay_env != "sandbox":
        print(json.dumps({"skipped": True, "reason": "sandbox_environment_required"}))
        return 2
    client = EbayClient(settings)
    report = sanitized_read_report(client)
    print(json.dumps(report, indent=2, default=str))
    if report.get("skipped"):
        return 2
    reads = report.get("reads") or {}
    return 0 if reads and all((v or {}).get("ok") for v in reads.values()) else 1


def cmd_simulated_e2e(args: argparse.Namespace) -> int:
    from firefinds.engine.simulated_e2e import run_simulated_e2e

    settings = get_settings()
    report = run_simulated_e2e(
        settings=settings,
        catalog_path=Path(args.catalog),
        privilege_path=Path(args.privilege),
        order_path=Path(args.order),
        out_dir=Path(args.out),
    )
    print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_order_ingest_dry_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = fixture_lifecycle(settings, Path(args.fixture), out)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("state") == "ROUTED_OFF" else 1


def cmd_poll_sandbox_orders(args: argparse.Namespace) -> int:
    from firefinds.engine.order_ingest import OrderIngest
    from firefinds.engine.order_poll import poll_orders
    from firefinds.engine.services import Audit
    settings = get_settings()
    if settings.ebay_env != "sandbox":
        print(json.dumps({"reason": "sandbox_environment_required"}))
        return 2
    out = Path(args.out)
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    client = EbayClient(settings)
    if not client.user_refresh_token_present():
        print(json.dumps({"reason": "user_refresh_token_missing"}))
        return 2
    ingest = OrderIngest(settings, Audit(out / "audit.jsonl"), out / "orders.json")
    report = poll_orders(client=client, ingest=ingest, sku_mapping=mapping,
                         progress_path=out / "poll.json", max_pages=args.max_pages)
    print(json.dumps(report, indent=2))
    return 0 if report["complete"] else 2
