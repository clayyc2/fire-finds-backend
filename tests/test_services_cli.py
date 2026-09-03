"""Ingest-stub / score / rank integration via services."""

from __future__ import annotations

from firefinds.config import Settings
from firefinds.services import ingest_stub, rank_candidates, score_all


def test_ingest_score_rank_flow(settings: Settings):
    n = ingest_stub(settings)
    assert n == 5
    # Rescore is idempotent
    updated = score_all(settings)
    assert updated == 5
    top = rank_candidates(10, settings=settings)
    assert len(top) >= 1
    # All returned must have passed
    for row in top:
        assert row["score"] > 0
    # Stub-001 and Stub-004 should pass with defaults
    skus = {r["sku"] for r in top}
    assert "FF-STUB-001" in skus
    assert "FF-STUB-004" in skus
    # Low profit / low stock stubs should not appear
    assert "FF-STUB-002" not in skus
    assert "FF-STUB-003" not in skus
    assert settings.actions_jsonl.is_file()
