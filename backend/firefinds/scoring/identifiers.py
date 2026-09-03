"""UPC/EAN checksum validation and MPN canonicalization."""

from __future__ import annotations

import re
from dataclasses import dataclass


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_MPN = re.compile(r"[^A-Za-z0-9\-_./]+")


def strip_spaces(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE_RE.sub("", str(value).strip())


def upc_ean_checksum_ok(code: str) -> bool:
    """Validate UPC-A (12), EAN-13 (13), or EAN-8 (8) check digit."""
    if not code.isdigit():
        return False
    n = len(code)
    if n not in (8, 12, 13):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    # Right-to-left: odd positions (1-based from right) * 3
    total = 0
    for i, d in enumerate(reversed(body), start=1):
        total += d * (3 if i % 2 == 1 else 1)
    calc = (10 - (total % 10)) % 10
    return calc == check


def normalize_upc(raw: str | None) -> tuple[str | None, bool]:
    """Return (normalized_upc_or_none, checksum_valid).

    Strips spaces; zero-pads common 11-digit UPC to 12 when checksum would pass.
    """
    code = strip_spaces(raw)
    if not code:
        return None, False
    # Keep digits only for checksum forms
    digits = re.sub(r"\D", "", code)
    if not digits:
        return None, False
    candidates = [digits]
    if len(digits) == 11:
        candidates.append(digits.zfill(12))
    if len(digits) == 12:
        candidates.append(digits.zfill(13))
    for cand in candidates:
        if upc_ean_checksum_ok(cand):
            return cand, True
    # Store stripped digits even if checksum fails (flag invalid)
    return digits, False


def canonicalize_mpn(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip().upper()
    text = _SPACE_RE.sub("", text)
    text = _NON_ALNUM_MPN.sub("", text)
    return text or None


@dataclass(frozen=True)
class NormalizedIds:
    upc_raw: str | None
    upc_norm: str | None
    upc_valid: bool
    mpn_raw: str | None
    mpn_norm: str | None


def normalize_product_ids(upc: str | None, mpn: str | None) -> NormalizedIds:
    upc_norm, upc_valid = normalize_upc(upc)
    mpn_norm = canonicalize_mpn(mpn)
    return NormalizedIds(
        upc_raw=str(upc).strip() if upc else None,
        upc_norm=upc_norm,
        upc_valid=upc_valid,
        mpn_raw=str(mpn).strip() if mpn else None,
        mpn_norm=mpn_norm,
    )
