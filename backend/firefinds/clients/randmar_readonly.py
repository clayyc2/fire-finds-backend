"""Fixed-account Randmar reads with no cart or supplier-order write surface."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, quote

from firefinds.config import Settings
from .randmar import RandmarClient, SupplierOrdersDisabled


class ReadOnlyRandmarClient(RandmarClient):
    def __init__(self, secrets_dir: Path, reseller_id: str):
        if not isinstance(reseller_id, str) or not reseller_id.strip():
            raise ValueError("Explicit reseller ID required")
        super().__init__(Settings(secrets_dir=Path(secrets_dir).resolve(),
                                 randmar_reseller_id=reseller_id,
                                 dry_run=True, global_kill_switch=True,
                                 supplier_orders_enabled=False))

    def _read_named_private(self, name):
        path = self.settings.secrets_dir / name
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Credentials must be private regular files")
        return self._read_secret_file(path)

    def _load_credentials(self):
        return (self._read_named_private("randmar_client_id.txt"),
                self._read_named_private("randmar_api_key.txt"))

    def get_product(self, sku):
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("Explicit supplier SKU required")
        return self._request_json("GET", self._reseller_path("/Product/" + quote(sku, safe="")))

    def get_manufacturer(self, manufacturer_id):
        if not isinstance(manufacturer_id, str) or not manufacturer_id.strip():
            raise ValueError("Explicit manufacturer required")
        return self._request_json("GET", self._reseller_path("/Manufacturer/" + quote(manufacturer_id, safe="")))

    def get_account(self):
        return self._request_json("GET", self._reseller_path("/Account/General"))

    def _request_json(self, method, url, **kwargs):
        parsed = urlsplit(url)
        base = self._reseller_path("").rstrip("/")
        allowed = (
            method == "POST" and parsed.query == "" and url == base + "/Report/Products/JSON"
        ) or (
            method == "GET" and parsed.query == "" and
            (url in {base + "/Products/InstantRebates", base + "/Orders/Shipments", base + "/Account/General"}
             or url.startswith(base + "/Order/")
             or any(url.startswith(base + prefix) and "/" not in url[len(base + prefix):]
                    for prefix in ("/Product/", "/Manufacturer/")))
        )
        if not allowed:
            raise SupplierOrdersDisabled("Read-only supplier client refuses this operation")
        return super()._request_json(method, url, **kwargs)
