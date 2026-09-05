"""Independent account inspection: matched credentials, no Sell writes.

OAuth refresh POSTs are necessary authentication, not commerce mutations.
This client never loads .env or accepts ambient credential/gate overrides.
"""
from pathlib import Path
import urllib.parse

from firefinds.config import Settings
from .ebay import EbayClient, EbayListingsDisabled


class ReadOnlyEbayClient(EbayClient):
    def __init__(self, environment: str, secrets_dir: Path):
        if environment not in {"sandbox", "production"}:
            raise ValueError("Explicit sandbox or production environment required")
        self._credential_environment = environment
        directory = Path(secrets_dir).resolve()
        super().__init__(Settings(
            ebay_env=environment,
            secrets_dir=directory,
            ebay_client_secret_file=directory / f"ebay_client_secret_{environment}.txt",
            ebay_user_refresh_token_file=directory / f"ebay_user_refresh_token_{environment}.txt",
            dry_run=True, global_kill_switch=True,
            live_listings_enabled=False, supplier_orders_enabled=False,
            ebay_production_enabled=False, ebay_sandbox_publish_enabled=False,
            ebay_tracking_updates_enabled=False,
            ebay_browse_use_production=False,
            retry_max_attempts=2,
        ))

    def _read_secret_file(self, path):
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Credential files must be private regular files")
        return super()._read_secret_file(path)

    def _load_credentials(self, *, for_browse=False):
        if for_browse:
            raise EbayListingsDisabled("Account inspection does not invoke Browse")
        directory = self.settings.secrets_dir
        environment = self._credential_environment
        return (
            self._read_secret_file(directory / f"ebay_client_id_{environment}.txt"),
            self._read_secret_file(directory / f"ebay_client_secret_{environment}.txt"),
        )

    def _assert_listings_allowed(self, *, publish=False):
        raise EbayListingsDisabled("Read-only account client refuses all listing writes")

    def _sell_json(self, method, path, **kwargs):
        if method.upper() != "GET" or kwargs.get("body") is not None:
            raise EbayListingsDisabled("Read-only account client refuses Sell mutations")
        if not path.startswith(("/account/v1/", "/inventory/v1/", "/fulfillment/v1/")):
            raise ValueError("Unrecognized account read path")
        return super()._sell_json(method, path, **kwargs)

    def get_offers_for_sku(self, sku):
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("Explicit merchant SKU required")
        query = urllib.parse.urlencode({"sku": sku})
        result = self._sell_json("GET", f"/inventory/v1/offer?{query}", op="getOffers")
        return result if isinstance(result, dict) else {}

    def get_inventory_item(self, sku):
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("Explicit merchant SKU required")
        result = self._sell_json("GET", f"/inventory/v1/inventory_item/{urllib.parse.quote(sku, safe='')}",
                                 op="getInventoryItem")
        return result if isinstance(result, dict) else {}
