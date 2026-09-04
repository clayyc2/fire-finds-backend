"""Deterministic Ops exception engine (no AI improvisation)."""

from firefinds.ops.exceptions import (
    EXCEPTION_RULES,
    RuleHit,
    evaluate_candidate,
    list_exceptions,
    scan_exceptions,
)

__all__ = [
    "EXCEPTION_RULES",
    "RuleHit",
    "evaluate_candidate",
    "list_exceptions",
    "scan_exceptions",
]
