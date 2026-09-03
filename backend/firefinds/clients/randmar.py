"""Randmar API client stub: OAuth client-credentials + Products/JSON.

Secrets are loaded from env or /workspace/firefinds/secrets/ when present.
This module never prints or logs secret values.
Order methods refuse unless SUPPLIER_ORDERS_ENABLED is true.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from firefinds.config import Settings, get_settings


class SupplierOrdersDisabled(RuntimeError):
    """Raised when an order method is called while the gate is off."""


class RandmarClient:
    """Minimal stub for Randmar auth + product catalog fetch."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._access_token: str | None = None

    def _read_secret_file(self, name: str) -> str | None:
        """Read a secret file if present; never echo contents to callers' logs."""
        path = self.settings.secrets_dir / name
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _load_credentials(self) -> tuple[str | None, str | None]:
        """Load client id/secret from env, then secrets dir files.

        File names tried: client_id / client_secret, and
        RANDMAR_CLIENT_ID / RANDMAR_CLIENT_SECRET.
        """
        client_id = os.environ.get("RANDMAR_CLIENT_ID") or self._read_secret_file(
            "client_id"
        ) or self._read_secret_file("RANDMAR_CLIENT_ID")
        client_secret = os.environ.get(
            "RANDMAR_CLIENT_SECRET"
        ) or self._read_secret_file("client_secret") or self._read_secret_file(
            "RANDMAR_CLIENT_SECRET"
        )
        return client_id, client_secret

    def credentials_present(self) -> bool:
        cid, secret = self._load_credentials()
        return bool(cid and secret)

    def fetch_token(self) -> str:
        """OAuth2 client-credentials token request.

        Returns access_token string. Raises if credentials missing or HTTP fails.
        Does not print secrets.
        """
        client_id, client_secret = self._load_credentials()
        if not client_id or not client_secret:
            raise RuntimeError(
                "Randmar credentials not found. Set RANDMAR_CLIENT_ID/"
                "RANDMAR_CLIENT_SECRET or place files under secrets/."
            )

        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.settings.randmar_token_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Do not include response body if it might echo credentials
            raise RuntimeError(
                f"Randmar token request failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Randmar token request failed: {exc.reason}") from None

        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Randmar token response missing access_token")
        self._access_token = str(token)
        return self._access_token

    def get_products_json(self, *, use_token: bool = True) -> Any:
        """GET {API_BASE}/Products/JSON (interface stub).

        When credentials are absent this raises rather than calling live.
        """
        token = self._access_token
        if use_token and not token:
            token = self.fetch_token()

        url = self.settings.randmar_api_base.rstrip("/") + "/Products/JSON"
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # Reseller id is not secret; include if API expects it as query/header
        reseller = self.settings.randmar_reseller_id
        if reseller:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}resellerId={urllib.parse.quote(reseller)}"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Randmar Products/JSON failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Randmar Products/JSON failed: {exc.reason}"
            ) from None

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        """Order placement — gated OFF by default."""
        if not self.settings.supplier_orders_enabled:
            raise SupplierOrdersDisabled(
                "SUPPLIER_ORDERS_ENABLED is false; refusing to place order"
            )
        raise NotImplementedError(
            "Live supplier orders are not implemented in this interim scaffold"
        )

    def create_supplier_order(self, *_args: Any, **_kwargs: Any) -> None:
        """Alias order method — same gate."""
        return self.place_order(*_args, **_kwargs)
