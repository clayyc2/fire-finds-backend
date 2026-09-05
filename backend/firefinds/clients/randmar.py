"""Randmar API client: OAuth client-credentials + catalog reads.

Secrets load from RANDMAR_CLIENT_SECRET_FILE / secrets path.
This module never prints or logs secret or token values.
Order methods refuse unless SUPPLIER_ORDERS_ENABLED is true.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from firefinds.config import Settings, get_settings

logger = logging.getLogger(__name__)


class SupplierOrdersDisabled(RuntimeError):
    """Raised when an order method is called while the gate is off."""


class RandmarClient:
    """Randmar auth + product catalog / instant-rebate fetch (read-only)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._access_token: str | None = None

    def _read_secret_file(self, path: Path) -> str | None:
        """Read a secret file if present; never echo contents."""
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _read_named_secret(self, name: str) -> str | None:
        return self._read_secret_file(self.settings.secrets_dir / name)

    def _load_credentials(self) -> tuple[str | None, str | None]:
        """Load client id/secret from env and secret files.

        Client id: RANDMAR_CLIENT_ID env, else settings / default,
        else secrets/randmar_client_id.txt, secrets/client_id,
        else secrets/RANDMAR_CLIENT_ID.

        Client secret: RANDMAR_CLIENT_SECRET env, else file pointed to by
        RANDMAR_CLIENT_SECRET_FILE / settings.randmar_client_secret_file,
        else secrets/randmar_api_key.txt, secrets/client_secret,
        secrets/RANDMAR_CLIENT_SECRET.
        """
        client_id = (
            os.environ.get("RANDMAR_CLIENT_ID")
            or self.settings.randmar_client_id
            or self._read_named_secret("randmar_client_id.txt")
            or self._read_named_secret("client_id")
            or self._read_named_secret("RANDMAR_CLIENT_ID")
        )
        # Prefer explicit env secret only if set (tests); production uses file.
        client_secret = os.environ.get("RANDMAR_CLIENT_SECRET")
        if not client_secret:
            secret_file = (
                os.environ.get("RANDMAR_CLIENT_SECRET_FILE")
                or (
                    str(self.settings.randmar_client_secret_file)
                    if self.settings.randmar_client_secret_file
                    else None
                )
            )
            if secret_file:
                client_secret = self._read_secret_file(Path(secret_file))
        if not client_secret:
            client_secret = (
                self._read_named_secret("randmar_api_key.txt")
                or self._read_named_secret("client_secret")
                or self._read_named_secret("RANDMAR_CLIENT_SECRET")
            )
        return (client_id or None), (client_secret or None)

    def credentials_present(self) -> bool:
        cid, secret = self._load_credentials()
        return bool(cid and secret)

    def fetch_token(self) -> str:
        """OAuth2 client-credentials token request.

        Returns access_token string. Raises if credentials missing or HTTP fails.
        Does not print or log secrets/tokens.
        """
        client_id, client_secret = self._load_credentials()
        if not client_id or not client_secret:
            raise RuntimeError(
                "Randmar credentials not found. Set RANDMAR_CLIENT_ID and "
                "RANDMAR_CLIENT_SECRET_FILE (or RANDMAR_CLIENT_SECRET), "
                "or place files under secrets/."
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
            raise RuntimeError(
                f"Randmar token request failed with HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Randmar token request failed: {exc.reason}") from None

        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Randmar token response missing access_token")
        self._access_token = str(token)
        logger.info("Randmar token acquired (value not logged)")
        return self._access_token

    def _auth_headers(self, *, use_token: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if use_token:
            token = self._access_token or self.fetch_token()
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _reseller_path(self, suffix: str) -> str:
        base = self.settings.randmar_api_base.rstrip("/")
        reseller = urllib.parse.quote(self.settings.randmar_reseller_id, safe="")
        suffix = suffix if suffix.startswith("/") else f"/{suffix}"
        return f"{base}/V4/Reseller/{reseller}{suffix}"

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        use_token: bool = True,
        timeout: int = 120,
        label: str = "Randmar API",
    ) -> Any:
        headers = self._auth_headers(use_token=use_token)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:240]
            except Exception:
                body = ""
            suffix = f": {body}" if body else ""
            raise RuntimeError(f"{label} failed with HTTP {exc.code}{suffix}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{label} failed: {exc.reason}") from None
        if not raw.strip():
            return None
        return json.loads(raw)

    def get_products_json(
        self,
        *,
        manufacturer_id: str | None = None,
        use_token: bool = True,
    ) -> Any:
        """POST /V4/Reseller/{id}/Report/Products/JSON (optional manufacturerId)."""
        url = self._reseller_path("/Report/Products/JSON")
        if manufacturer_id:
            qs = urllib.parse.urlencode({"manufacturerId": manufacturer_id})
            url = f"{url}?{qs}"
        return self._request_json(
            "POST",
            url,
            data=b"{}",
            use_token=use_token,
            timeout=180,
            label="Randmar Products/JSON",
        )

    def get_instant_rebates(self, *, use_token: bool = True) -> Any:
        """GET /V4/Reseller/{id}/Products/InstantRebates."""
        url = self._reseller_path("/Products/InstantRebates")
        return self._request_json(
            "GET",
            url,
            use_token=use_token,
            timeout=60,
            label="Randmar InstantRebates",
        )


    # --- read-only shipping quotes (never Process / place order) -----------

    def cart_add_item_default(
        self,
        cart_name: str,
        sku: str,
        *,
        quantity: int = 1,
    ) -> Any:
        """POST Cart/AddItem/.../DefaultOpportunity — mutates quote cart only."""
        from urllib.parse import quote

        cart = quote(cart_name, safe="")
        sku_q = quote(str(sku), safe="")
        url = self._reseller_path(
            f"/Cart/AddItem/{cart}/{sku_q}/DefaultOpportunity"
        )
        qs = urllib.parse.urlencode({"quantity": int(quantity)})
        url = f"{url}?{qs}"
        return self._request_json(
            "POST", url, data=b"", timeout=60, label="Randmar Cart/AddItem"
        )

    def cart_get(self, cart_name: str) -> Any:
        from urllib.parse import quote

        url = self._reseller_path(f"/Cart/{quote(cart_name, safe='')}")
        return self._request_json(
            "GET", url, timeout=60, label="Randmar Cart/GET"
        )

    def cart_delete(self, cart_name: str) -> Any:
        from urllib.parse import quote

        url = self._reseller_path(f"/Cart/{quote(cart_name, safe='')}")
        return self._request_json(
            "DELETE", url, timeout=60, label="Randmar Cart/DELETE"
        )

    def cart_shipping_methods(
        self,
        cart_name: str,
        ship_to: dict[str, Any],
    ) -> Any:
        """POST Cart/ShippingMethods — quote only; never Process."""
        from urllib.parse import quote

        url = self._reseller_path(
            f"/Cart/ShippingMethods/{quote(cart_name, safe='')}"
        )
        # ShipToDetails.ShipTo = ShipToLocation (additionalProperties=false).
        from firefinds.scoring.shipping import shipto_for_api

        body = {"ShipTo": shipto_for_api(ship_to)}
        return self._request_json(
            "POST",
            url,
            data=json.dumps(body).encode("utf-8"),
            timeout=90,
            label="Randmar Cart/ShippingMethods",
        )

    def shipping_label_estimate(self, shipment_details: dict[str, Any]) -> Any:
        """POST ShippingLabel/Estimate — quote only; never Generate."""
        url = self._reseller_path("/ShippingLabel/Estimate")
        return self._request_json(
            "POST",
            url,
            data=json.dumps(shipment_details).encode("utf-8"),
            timeout=90,
            label="Randmar ShippingLabel/Estimate",
        )

    def estimate_cart_shipping(
        self,
        sku: str,
        *,
        ship_to: dict[str, Any],
        cart_prefix: str = "ff-ship-quote",
        quantity: int = 1,
    ):
        """Add SKU to ephemeral cart, quote ShippingMethods, delete cart.

        Never calls Cart/Process*. Returns ShippingQuote.
        """
        from firefinds.scoring.shipping import parse_cart_shipping_methods

        cart_name = f"{cart_prefix}-{sku}"[:80]
        try:
            self.cart_add_item_default(cart_name, sku, quantity=quantity)
            payload = self.cart_shipping_methods(cart_name, ship_to)
            return parse_cart_shipping_methods(payload)
        finally:
            try:
                self.cart_delete(cart_name)
            except Exception:
                pass

    def estimate_cart_shipping_multi(
        self,
        sku: str,
        *,
        ship_tos: list[dict[str, Any]],
        cart_prefix: str = "ff-ship-quote",
        quantity: int = 1,
        sleep_sec: float = 0.0,
    ):
        """Add SKU once, quote ShippingMethods for each dest, delete cart.

        Never calls Cart/Process*. Returns list[ShippingQuote] aligned to ship_tos.
        """
        import time

        from firefinds.scoring.shipping import (
            ShippingQuote,
            parse_cart_shipping_methods,
        )

        cart_name = f"{cart_prefix}-{sku}"[:80]
        quotes = []
        try:
            try:
                self.cart_delete(cart_name)
            except Exception:
                pass
            self.cart_add_item_default(cart_name, sku, quantity=quantity)
            for i, ship_to in enumerate(ship_tos):
                if i and sleep_sec > 0:
                    time.sleep(float(sleep_sec))
                try:
                    payload = self.cart_shipping_methods(cart_name, ship_to)
                    quotes.append(parse_cart_shipping_methods(payload))
                except Exception as exc:  # noqa: BLE001
                    quotes.append(
                        ShippingQuote.unresolved(
                            reason=f"cart_shipping_methods_error:{type(exc).__name__}",
                            source="cart_shipping_methods",
                        )
                    )
            return quotes
        finally:
            try:
                self.cart_delete(cart_name)
            except Exception:
                pass

    def estimate_shipping_label(
        self,
        product: dict[str, Any],
        *,
        ship_to: dict[str, Any],
        warehouse: str | None = None,
    ):
        """ShippingLabel/Estimate using warehouse origin + UnitWeight."""
        from firefinds.scoring.shipping import (
            WAREHOUSE_ORIGINS,
            parse_shipvia_estimates,
            pick_fulfillment_warehouse,
        )

        wh = warehouse or pick_fulfillment_warehouse(product)
        origin = WAREHOUSE_ORIGINS.get(wh or "", WAREHOUSE_ORIGINS["Toronto"])
        try:
            weight = float(product.get("unit_weight") or product.get("UnitWeight") or 0)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            from firefinds.scoring.shipping import ShippingQuote

            return ShippingQuote.unresolved(
                reason="missing_unit_weight_for_label_estimate",
                warehouse=wh,
                source="shipping_label_estimate",
            )
        from firefinds.scoring.shipping import shipto_for_api

        to_addr = shipto_for_api(ship_to)
        details = {
            "From": origin,
            "To": to_addr,
            "NumberOfBoxes": 1,
            "TotalWeight": weight,
            "ReferenceNumber": str(product.get("sku") or ""),
            "WithZPLThermalShippingLabels": False,
        }
        payload = self.shipping_label_estimate(details)
        return parse_shipvia_estimates(payload)

    def _request_bytes(
        self,
        method: str,
        url: str,
        *,
        use_token: bool = False,
        timeout: int = 120,
        label: str = "Randmar API",
        accept: str = "*/*",
    ) -> tuple[bytes, str]:
        """GET binary body + Content-Type. Default anonymous (public Product/Image)."""
        headers = self._auth_headers(use_token=use_token)
        headers["Accept"] = accept
        # Avoid forcing JSON content-type on binary GETs
        headers.pop("Content-Type", None)
        req = urllib.request.Request(url, data=None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") or ""
                return raw, ctype
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:240]
            except Exception:
                body = ""
            suffix = f": {body}" if body else ""
            raise RuntimeError(f"{label} failed with HTTP {exc.code}{suffix}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{label} failed: {exc.reason}") from None

    def get_product_images(self, sku: str, *, use_token: bool = False) -> list[dict[str, Any]]:
        """GET /Product/{sku}/Images — list existing product images (read-only).

        Public ProductImageInfo list (Url, ImageId, IsPrimary, …). Works
        anonymously (OpenAPI Public) and with reseller OAuth. Prefer this over
        manufacturer Images (reseller auth → 401) and never call GenerateImage /
        AppendImage / upload POSTs. Default use_token=False (no Integration secret).
        """
        from urllib.parse import quote

        base = self.settings.randmar_api_base.rstrip("/")
        url = f"{base}/Product/{quote(str(sku), safe='')}/Images"
        payload = self._request_json(
            "GET",
            url,
            use_token=use_token,
            timeout=60,
            label="Randmar Product/Images",
        )
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        raise RuntimeError("Randmar Product/Images returned unexpected payload shape")

    def download_product_image(
        self,
        sku: str,
        image_id: str,
        *,
        use_token: bool = False,
    ) -> tuple[bytes, str]:
        """GET /Product/{sku}/Image/{imageId} — download still bytes (read-only).

        Public endpoint; default anonymous. Returns (body, content_type).
        """
        from urllib.parse import quote

        base = self.settings.randmar_api_base.rstrip("/")
        url = (
            f"{base}/Product/{quote(str(sku), safe='')}"
            f"/Image/{quote(str(image_id), safe='')}"
        )
        return self._request_bytes(
            "GET",
            url,
            use_token=use_token,
            timeout=120,
            label="Randmar Product/Image",
            accept="image/*,*/*",
        )

    def get_manufacturer_product_images(
        self,
        manufacturer_id: str,
        sku: str,
        *,
        use_token: bool = True,
    ) -> list[dict[str, Any]]:
        """GET /V4/Manufacturer/{mfrId}/Product/{sku}/Images (read-only list).

        Reseller credentials typically receive HTTP 401/403. Prefer
        get_product_images() for catalog backfill.
        """
        from urllib.parse import quote

        base = self.settings.randmar_api_base.rstrip("/")
        mid = quote(str(manufacturer_id), safe="")
        sku_q = quote(str(sku), safe="")
        url = f"{base}/V4/Manufacturer/{mid}/Product/{sku_q}/Images"
        payload = self._request_json(
            "GET",
            url,
            use_token=use_token,
            timeout=60,
            label="Randmar Manufacturer Product/Images",
        )
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        raise RuntimeError(
            "Randmar Manufacturer Product/Images returned unexpected payload shape"
        )

    def process_cart(self, cart_name: str, payload: dict[str, Any]) -> Any:
        """Submit an already validated cart through Randmar's supported API.

        This is the irreversible supplier-order boundary.  It is fail-closed in
        dry-run, while the global kill switch is set, or while supplier orders
        are disabled.  The caller supplies the Randmar-approved Process payload;
        this client never invents shipping/payment fields.
        """
        if not self.settings.supplier_orders_enabled:
            raise SupplierOrdersDisabled(
                "SUPPLIER_ORDERS_ENABLED is false; refusing to place order"
            )
        if self.settings.dry_run:
            raise SupplierOrdersDisabled("DRY_RUN is true; refusing to place order")
        if self.settings.global_kill_switch:
            raise SupplierOrdersDisabled(
                "GLOBAL_KILL_SWITCH is true; refusing to place order"
            )
        from urllib.parse import quote
        url = self._reseller_path(f"/Cart/ProcessNew/{quote(cart_name, safe='')}")
        return self._request_json(
            "POST", url, data=json.dumps(payload).encode("utf-8"), timeout=120,
            label="Randmar Cart/ProcessNew",
        )

    def get_order_by_po(self, reseller_po_number: str) -> Any:
        """Read an existing order by our immutable eBay order id/PO."""
        from urllib.parse import quote
        url = self._reseller_path(
            f"/Order/PONumber/{quote(reseller_po_number, safe='')}"
        )
        return self._request_json("GET", url, timeout=60, label="Randmar Order/PO")

    def get_order(self, order_number: str) -> Any:
        """Read Randmar order status/tracking; never mutates supplier state."""
        from urllib.parse import quote
        url = self._reseller_path(f"/Order/{quote(order_number, safe='')}")
        return self._request_json("GET", url, timeout=60, label="Randmar Order/GET")

    def list_shipments(self) -> Any:
        """Read shipment/tracking rows; never mutates supplier state."""
        url = self._reseller_path("/Orders/Shipments")
        return self._request_json(
            "GET", url, timeout=60, label="Randmar Orders/Shipments"
        )

    def place_order(
        self,
        cart_name: str | None = None,
        payload: dict[str, Any] | None = None,
        **legacy: Any,
    ) -> Any:
        """Compatibility wrapper for the gated Process boundary.

        Legacy ``sku``/``qty`` calls remain refused: an approved cart and the
        exact Randmar Process payload are mandatory.
        """
        if cart_name is None or payload is None:
            if not self.settings.supplier_orders_enabled:
                raise SupplierOrdersDisabled(
                    "SUPPLIER_ORDERS_ENABLED is false; refusing to place order"
                )
            raise NotImplementedError(
                "Direct SKU ordering is unsupported; build and validate a cart first"
            )
        return self.process_cart(cart_name, payload)

    def create_supplier_order(self, *args: Any, **kwargs: Any) -> Any:
        """Alias order method — same gate."""
        return self.place_order(*args, **kwargs)


def extract_rebate_amount(instant_rebate: Any) -> float:
    """Normalize InstantRebate field (dict with RebateAmount, or number)."""
    if instant_rebate is None:
        return 0.0
    if isinstance(instant_rebate, dict):
        try:
            return float(instant_rebate.get("RebateAmount") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(instant_rebate)
    except (TypeError, ValueError):
        return 0.0


def normalize_randmar_product(
    raw: dict[str, Any],
    *,
    rebate: float = 0.0,
) -> dict[str, Any]:
    """Map a Randmar product row to internal ingest fields."""
    sku = raw.get("RandmarSKU") or raw.get("sku")
    dealer = raw.get("Price")
    if dealer is None:
        dealer = raw.get("RegularPrice")
    if dealer is None:
        dealer = raw.get("dealer_cost")
    stock = raw.get("AvailableQuantity")
    if stock is None:
        stock = raw.get("stock")
    def _qi(key: str) -> int:
        try:
            return int(raw.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    try:
        unit_weight = float(raw.get("UnitWeight") or 0) or None
    except (TypeError, ValueError):
        unit_weight = None

    return {
        "sku": str(sku) if sku is not None else "",
        "upc": raw.get("UPC") or raw.get("upc"),
        "mpn": raw.get("MPN") or raw.get("mpn"),
        "manufacturer": raw.get("ManufacturerName") or raw.get("manufacturer"),
        "map": raw.get("MAP") if raw.get("MAP") is not None else raw.get("map"),
        "msrp": raw.get("MSRP") if raw.get("MSRP") is not None else raw.get("msrp"),
        "dealer_cost": dealer,
        "rebate": rebate,
        "stock": stock if stock is not None else 0,
        "landed_cost": dealer,  # net only until shipping quote resolves
        "net_cost": dealer,
        "title": raw.get("Title") or raw.get("RandmarTitle"),
        "category": raw.get("Category") or raw.get("category"),
        "product_type": raw.get("ProductType") or raw.get("product_type"),
        "opportunity_only": bool(raw.get("OpportunityOnly") or False),
        "unit_weight": unit_weight,
        "qty_montreal": _qi("QuantityMontreal"),
        "qty_toronto": _qi("QuantityToronto"),
        "qty_vancouver": _qi("QuantityVancouver"),
        "qty_laval": _qi("QuantityLaval"),
        "qty_edmonton": _qi("QuantityEdmonton"),
    }
