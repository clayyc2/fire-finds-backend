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
    client = EbayClient(settings)
    report = sanitized_read_report(client)
    print(json.dumps(report, indent=2, default=str))
    if report.get("skipped"):
        return 0
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
