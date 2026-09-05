"""Bounded retry policy for read requests only."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def read_retry_delay(error, attempt: int, attempts: int) -> float | None:
    if error.code not in {429, 500, 502, 503, 504} or attempt >= attempts - 1:
        return None
    raw = error.headers.get("Retry-After") if error.headers else None
    if raw:
        try:
            delay = float(raw)
        except ValueError:
            try:
                until = parsedate_to_datetime(raw)
                delay = (until - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return None
        # A long delay must be deferred to a later run, never shortened.
        if not math.isfinite(delay) or delay > 60:
            return None
        return max(0.0, delay)
    return min(30.0, 2.0 ** attempt)
