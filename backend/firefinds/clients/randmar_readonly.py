"""Fixed-account Randmar reads with no cart or supplier-order write surface."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

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

    def _request_json(self, method, url, **kwargs):
        parsed = urlsplit(url)
        base = self._reseller_path("").rstrip("/")
        allowed = (
            method == "POST" and parsed.query == "" and url == base + "/Report/Products/JSON"
        ) or (
            method == "GET" and parsed.query == "" and
            (url in {base + "/Products/InstantRebates", base + "/Orders/Shipments"}
             or url.startswith(base + "/Order/"))
        )
        if not allowed:
            raise SupplierOrdersDisabled("Read-only supplier client refuses this operation")
        return super()._request_json(method, url, **kwargs)
