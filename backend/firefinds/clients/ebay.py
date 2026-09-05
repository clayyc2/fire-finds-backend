"""eBay API client: Browse competition (read-only) + gated Sell Inventory/Offer.

Browse uses OAuth client-credentials (application token).
Sell user OAuth (authorization code → refresh token) is implemented for
sandbox. Sandbox inventory/offer writes are allowed when a user refresh
token is present without LIVE_LISTINGS_ENABLED; publish stays refused
unless EBAY_SANDBOX_PUBLISH_ENABLED=true. Production Sell stays behind
EBAY_PRODUCTION_ENABLED + LIVE_LISTINGS_ENABLED. Secrets are never printed.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from firefinds.config import Settings, get_settings

logger = logging.getLogger(__name__)

BROWSE_SCOPE = "https://api.ebay.com/oauth/api_scope"
PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
PRODUCTION_BROWSE_BASE = "https://api.ebay.com/buy/browse/v1"
SANDBOX_BROWSE_BASE = "https://api.sandbox.ebay.com/buy/browse/v1"
PRODUCTION_SELL_BASE = "https://api.ebay.com/sell"
SANDBOX_SELL_BASE = "https://api.sandbox.ebay.com/sell"
PRODUCTION_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
SANDBOX_AUTH_URL = "https://auth.sandbox.ebay.com/oauth2/authorize"

# Minimal Sell user scopes (omit sell.marketing — not required for inventory/offers).
SELL_USER_SCOPES: tuple[str, ...] = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
)


class EbayCredentialsMissing(RuntimeError):
    """Raised when eBay client id/secret are not configured."""


class EbayListingsDisabled(RuntimeError):
    """Raised when Sell listing mutations are gated off."""


class EbayPublishDisabled(RuntimeError):
    """Raised when sandbox publish is gated off."""


class EbayFulfillmentDisabled(RuntimeError):
    """Raised when a tracking/fulfillment mutation is gated off."""


class EbayUserOAuthNotConfigured(RuntimeError):
    """Raised when RuName or user refresh token is missing."""


class EbayApiError(RuntimeError):
    """Sell/Browse API HTTP error with secrets-free details."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_id: int | str | None = None,
        error_name: str | None = None,
        raw_errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.error_name = error_name
        self.raw_errors = raw_errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "status": self.status,
            "error_id": self.error_id,
            "error_name": self.error_name,
            "errors": [
                {
                    "errorId": e.get("errorId"),
                    "message": e.get("message"),
                    "longMessage": e.get("longMessage"),
                    "domain": e.get("domain"),
                    "category": e.get("category"),
                }
                for e in self.raw_errors
                if isinstance(e, dict)
            ],
        }


@dataclass(frozen=True)
class CompetitionSnapshot:
    """Normalized Browse search competition stats for one query."""

    query: str
    query_type: str  # upc | mpn | title
    item_count: int
    lowest_price: float | None
    median_price: float | None
    sample_url: str | None
    currency: str | None = "CAD"
    raw_total: int = 0

    @property
    def found(self) -> bool:
        return self.item_count > 0 and self.lowest_price is not None


def _setup_instructions() -> str:
    return (
        "eBay credentials missing. Set up Browse API access:\n"
        "  1. Create an eBay developer application (production app keyset for CA Browse).\n"
        "  2. Set EBAY_CLIENT_ID in .env (App ID).\n"
        "  3. Write the Cert ID to a local file and set EBAY_CLIENT_SECRET_FILE "
        "(e.g. secrets/ebay_client_secret.txt). Never commit secrets.\n"
        "  4. Optional: EBAY_ENV=sandbox|production (default sandbox for Sell);\n"
        "     Browse competition uses a production app token when "
        "EBAY_BROWSE_USE_PRODUCTION=true (default).\n"
        "  5. EBAY_MARKETPLACE_ID=EBAY_CA\n"
        "LIVE_LISTINGS_ENABLED must remain false; Sell publish stays gated."
    )


class EbayClient:
    """Browse search (read-only) + Sell Sandbox stubs (gated)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._app_token: str | None = None
        self._user_access_token: str | None = None
        self._user_access_token_expires_at: float = 0.0

    # --- credentials -----------------------------------------------------

    def _read_secret_file(self, path: Path) -> str | None:
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _load_credentials(
        self, *, for_browse: bool = False
    ) -> tuple[str | None, str | None]:
        """Load App ID + Cert. Prefer Production files for Browse when enabled."""
        secrets_dir = self.settings.secrets_dir
        use_prod_browse = bool(
            for_browse and self.settings.ebay_browse_use_production
        )
        if use_prod_browse:
            client_id = (
                os.environ.get("EBAY_CLIENT_ID_PRODUCTION")
                or self._read_secret_file(secrets_dir / "ebay_client_id_production.txt")
            )
            client_secret = os.environ.get("EBAY_CLIENT_SECRET_PRODUCTION")
            if not client_secret:
                client_secret = self._read_secret_file(
                    secrets_dir / "ebay_client_secret_production.txt"
                )
            if client_id and client_secret:
                return client_id.strip() or None, client_secret
            # fall through to default pair if production files missing

        client_id = (
            os.environ.get("EBAY_CLIENT_ID")
            or self.settings.ebay_client_id
        )
        if client_id:
            client_id = client_id.strip() or None

        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_secret:
            secret_file = (
                os.environ.get("EBAY_CLIENT_SECRET_FILE")
                or (
                    str(self.settings.ebay_client_secret_file)
                    if self.settings.ebay_client_secret_file
                    else None
                )
            )
            if secret_file:
                client_secret = self._read_secret_file(Path(secret_file))
        if not client_secret:
            for name in (
                "ebay_client_secret.txt",
                "ebay_client_secret_sandbox.txt",
                "ebay_cert_id.txt",
                "EBAY_CLIENT_SECRET",
            ):
                client_secret = self._read_secret_file(secrets_dir / name)
                if client_secret:
                    break
        return client_id, client_secret

    def credentials_present(self) -> bool:
        cid, secret = self._load_credentials()
        return bool(cid and secret)

    def require_credentials(self) -> None:
        if not self.credentials_present():
            raise EbayCredentialsMissing(_setup_instructions())

    # --- OAuth app token (client credentials) ----------------------------

    def _token_url(self, *, for_browse: bool) -> str:
        # Browse CA competition may use production app token even when Sell
        # env is sandbox.
        if for_browse and self.settings.ebay_browse_use_production:
            return PRODUCTION_TOKEN_URL
        if self.settings.ebay_env == "production":
            return PRODUCTION_TOKEN_URL
        return SANDBOX_TOKEN_URL

    def _browse_base(self) -> str:
        if self.settings.ebay_browse_use_production:
            return PRODUCTION_BROWSE_BASE
        if self.settings.ebay_env == "production":
            return PRODUCTION_BROWSE_BASE
        return SANDBOX_BROWSE_BASE

    def _sell_base(self) -> str:
        # Select the host by credential environment, never by write permission.
        # A disabled production gate must not send production tokens to Sandbox.
        # Mutation methods enforce their own gates before reaching this transport.
        if self.settings.ebay_env == "production":
            return PRODUCTION_SELL_BASE
        if self.settings.ebay_env == "sandbox":
            return SANDBOX_SELL_BASE
        raise ValueError("Unknown eBay Sell environment")

    def fetch_app_token(self, *, for_browse: bool = True) -> str:
        """OAuth2 client-credentials application token. Never logs secrets."""
        self.require_credentials()
        client_id, client_secret = self._load_credentials(for_browse=for_browse)
        assert client_id and client_secret

        basic = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "scope": BROWSE_SCOPE,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self._token_url(for_browse=for_browse),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Do not include response body if it might echo credentials.
            raise RuntimeError(
                f"eBay token request failed: HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(f"eBay token request failed: {exc.reason}") from None

        token = payload.get("access_token")
        if not token:
            raise RuntimeError("eBay token response missing access_token")
        self._app_token = str(token)
        return self._app_token

    def _app_auth_header(self, *, for_browse: bool = True) -> dict[str, str]:
        if not self._app_token:
            self.fetch_app_token(for_browse=for_browse)
        return {
            "Authorization": f"Bearer {self._app_token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.settings.ebay_marketplace_id,
        }

    # --- Browse: competition search --------------------------------------

    def search_item_summary(
        self,
        *,
        q: str | None = None,
        gtin: str | None = None,
        limit: int = 50,
        filter_expr: str | None = "buyingOptions:{FIXED_PRICE}",
    ) -> dict[str, Any]:
        """GET /item_summary/search — read-only competition lookup."""
        self.require_credentials()
        params: dict[str, str] = {
            "limit": str(max(1, min(int(limit), 200))),
        }
        if gtin:
            params["gtin"] = str(gtin).strip()
        elif q:
            params["q"] = str(q).strip()
        else:
            raise ValueError("search_item_summary requires q or gtin")
        if filter_expr:
            params["filter"] = filter_expr

        url = (
            f"{self._browse_base()}/item_summary/search?"
            + urllib.parse.urlencode(params)
        )
        headers = self._app_auth_header(for_browse=True)
        req = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                # Refresh once
                self._app_token = None
                headers = self._app_auth_header(for_browse=True)
                req = urllib.request.Request(url, method="GET", headers=headers)
                with urllib.request.urlopen(req, timeout=45) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            raise RuntimeError(
                f"eBay Browse search failed: HTTP {exc.code}"
            ) from None

    @staticmethod
    def _extract_prices(payload: Mapping[str, Any] | Any) -> tuple[list[float], list[str], int]:
        items = []
        if isinstance(payload, dict):
            items = payload.get("itemSummaries") or []
            total = int(payload.get("total") or len(items) or 0)
        else:
            total = 0
        prices: list[float] = []
        urls: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            price_obj = item.get("price") or {}
            value = price_obj.get("value") if isinstance(price_obj, dict) else None
            try:
                if value is not None:
                    prices.append(float(value))
            except (TypeError, ValueError):
                pass
            href = item.get("itemWebUrl") or item.get("itemHref")
            if href:
                urls.append(str(href))
        return prices, urls, total

    def competition_for_product(
        self,
        product: dict[str, Any],
        *,
        top_n: int | None = None,
    ) -> CompetitionSnapshot:
        """Search CA marketplace by UPC else MPN/title; return price stats."""
        top_n = top_n if top_n is not None else self.settings.ebay_comp_top_n
        upc = (product.get("upc") or "").strip() if product.get("upc") else ""
        mpn = (product.get("mpn") or "").strip() if product.get("mpn") else ""
        title = (product.get("title") or "").strip() if product.get("title") else ""
        manufacturer = (
            (product.get("manufacturer") or "").strip()
            if product.get("manufacturer")
            else ""
        )

        query = ""
        query_type = "title"
        payload: dict[str, Any]

        if upc:
            query = upc
            query_type = "upc"
            payload = self.search_item_summary(gtin=upc, limit=max(top_n, 20))
            # Fallback to keyword if gtin returns nothing
            prices, urls, total = self._extract_prices(payload)
            if not prices:
                payload = self.search_item_summary(q=upc, limit=max(top_n, 20))
        elif mpn:
            query = f"{manufacturer} {mpn}".strip() if manufacturer else mpn
            query_type = "mpn"
            payload = self.search_item_summary(q=query, limit=max(top_n, 20))
        elif title:
            query = title
            query_type = "title"
            payload = self.search_item_summary(q=query, limit=max(top_n, 20))
        elif manufacturer:
            query = manufacturer
            query_type = "title"
            payload = self.search_item_summary(q=query, limit=max(top_n, 20))
        else:
            return CompetitionSnapshot(
                query="",
                query_type="none",
                item_count=0,
                lowest_price=None,
                median_price=None,
                sample_url=None,
                raw_total=0,
            )

        prices, urls, total = self._extract_prices(payload)
        if not prices:
            return CompetitionSnapshot(
                query=query,
                query_type=query_type,
                item_count=0,
                lowest_price=None,
                median_price=None,
                sample_url=urls[0] if urls else None,
                raw_total=total,
            )

        prices_sorted = sorted(prices)
        window = prices_sorted[: max(1, top_n)]
        lowest = window[0]
        median = float(statistics.median(window))
        return CompetitionSnapshot(
            query=query,
            query_type=query_type,
            item_count=len(prices_sorted),
            lowest_price=lowest,
            median_price=median,
            sample_url=urls[0] if urls else None,
            raw_total=total,
        )

    # --- Sell Sandbox stubs (gated) --------------------------------------

    def _assert_listings_allowed(self, *, publish: bool = False) -> None:
        """Gate Sell writes.

        Sandbox inventory/offer: allowed when user refresh token is present
        (or LIVE_LISTINGS_ENABLED) — does **not** require LIVE_LISTINGS_ENABLED.
        Sandbox publish: refused unless EBAY_SANDBOX_PUBLISH_ENABLED=true.
        Production Sell: requires EBAY_PRODUCTION_ENABLED + LIVE_LISTINGS_ENABLED.
        Every write also requires DRY_RUN=false and GLOBAL_KILL_SWITCH=false.
        """
        if self.settings.dry_run or self.settings.global_kill_switch:
            error = EbayPublishDisabled if publish else EbayListingsDisabled
            raise error("Listing write refused: DRY_RUN or GLOBAL_KILL_SWITCH is active")
        is_production = self.settings.ebay_env == "production"

        if is_production:
            if not self.settings.ebay_production_enabled:
                raise EbayListingsDisabled(
                    "EBAY_PRODUCTION_ENABLED is false; refusing production Sell calls."
                )
            if not self.settings.live_listings_enabled:
                raise EbayListingsDisabled(
                    "LIVE_LISTINGS_ENABLED is false; refusing production Sell "
                    "inventory/offer/publish."
                )
            return

        # sandbox
        if publish:
            if not self.settings.ebay_sandbox_publish_enabled:
                raise EbayPublishDisabled(
                    "EBAY_SANDBOX_PUBLISH_ENABLED is false; refusing publish even in "
                    "sandbox. Default is off."
                )
            return

        # sandbox inventory / offer
        if self.user_refresh_token_present():
            return
        if self.settings.live_listings_enabled:
            return
        raise EbayListingsDisabled(
            "Sandbox Sell inventory/offer requires a stored user refresh token "
            "(ebay-oauth-exchange) while LIVE_LISTINGS_ENABLED is false. "
            "Publish remains gated by EBAY_SANDBOX_PUBLISH_ENABLED."
        )

    # --- User OAuth (authorization code → refresh token) -----------------

    def _auth_authorize_url(self) -> str:
        if self.settings.ebay_env == "production":
            return PRODUCTION_AUTH_URL
        return SANDBOX_AUTH_URL

    def _user_token_url(self) -> str:
        """Token endpoint for user OAuth (follows EBAY_ENV, not Browse)."""
        if self.settings.ebay_env == "production":
            return PRODUCTION_TOKEN_URL
        return SANDBOX_TOKEN_URL

    def _resolve_runame(self) -> str | None:
        runame = self.settings.ebay_runame
        if runame and str(runame).strip():
            return str(runame).strip()
        env = (
            os.environ.get("EBAY_RUNAME")
            or os.environ.get("EBAY_REDIRECT_URI")
            or ""
        ).strip()
        return env or None

    def require_runame(self) -> str:
        runame = self._resolve_runame()
        if not runame:
            raise EbayUserOAuthNotConfigured(
                "EBAY_RUNAME (or EBAY_REDIRECT_URI) is required for user OAuth. "
                "Create a RuName in the eBay Developer Portal under User tokens "
                "/ Get a Token from eBay via Your Application (sandbox), then "
                "paste the RuName value into .env."
            )
        return runame

    def _refresh_token_path(self) -> Path:
        configured = self.settings.ebay_user_refresh_token_file
        if configured is not None:
            return Path(configured)
        env = os.environ.get("EBAY_USER_REFRESH_TOKEN_FILE")
        if env:
            return Path(env)
        return self.settings.secrets_dir / "ebay_user_refresh_token.txt"

    def user_refresh_token_present(self) -> bool:
        path = self._refresh_token_path()
        if not path.is_file():
            return False
        try:
            return bool(path.read_text(encoding="utf-8").strip())
        except OSError:
            return False

    def _read_refresh_token(self) -> str | None:
        path = self._refresh_token_path()
        return self._read_secret_file(path)

    def _store_refresh_token(self, refresh_token: str) -> Path:
        """Write refresh token to secrets file with mode 600. Never logs value."""
        path = self._refresh_token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(refresh_token.strip() + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def _basic_auth_header(self) -> str:
        self.require_credentials()
        client_id, client_secret = self._load_credentials()
        assert client_id and client_secret
        return "Basic " + base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")

    def _post_token_form(self, form: dict[str, str]) -> dict[str, Any]:
        body = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(
            self._user_token_url(),
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": self._basic_auth_header(),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"eBay user token request failed: HTTP {exc.code}"
            ) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"eBay user token request failed: {exc.reason}"
            ) from None

    def build_auth_url(
        self,
        *,
        scopes: tuple[str, ...] | list[str] | None = None,
        state: str | None = None,
    ) -> str:
        """Build sandbox/production authorize URL for Sell user consent."""
        self.require_credentials()
        runame = self.require_runame()
        client_id, _ = self._load_credentials()
        assert client_id
        scope_list = tuple(scopes) if scopes else SELL_USER_SCOPES
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": runame,
            "response_type": "code",
            "scope": " ".join(scope_list),
        }
        if state:
            params["state"] = state
        return f"{self._auth_authorize_url()}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for tokens; store refresh token (mode 600).

        Returns a secrets-free status dict. Never includes token values.
        """
        raw_code = (code or "").strip()
        if not raw_code:
            raise ValueError("authorization code is required")
        # Browser redirects may leave the code URL-encoded; decode once.
        if "%" in raw_code:
            raw_code = urllib.parse.unquote(raw_code)
        runame = self.require_runame()
        payload = self._post_token_form(
            {
                "grant_type": "authorization_code",
                "code": raw_code,
                "redirect_uri": runame,
            }
        )
        refresh = payload.get("refresh_token")
        access = payload.get("access_token")
        if not refresh:
            raise RuntimeError("eBay token response missing refresh_token")
        if not access:
            raise RuntimeError("eBay token response missing access_token")
        path = self._store_refresh_token(str(refresh))
        expires_in = int(payload.get("expires_in") or 7200)
        self._user_access_token = str(access)
        self._user_access_token_expires_at = time.time() + max(60, expires_in - 60)
        return {
            "ok": True,
            "refresh_token_stored": True,
            "refresh_token_path": str(path),
            "refresh_token_present": True,
            "access_token_cached": True,
            "expires_in": expires_in,
            "token_type": payload.get("token_type"),
            "scope": payload.get("scope"),
            "ebay_env": self.settings.ebay_env,
        }

    def refresh_user_token(self) -> str:
        """Use stored refresh token to obtain a user access token."""
        refresh = self._read_refresh_token()
        if not refresh:
            raise EbayUserOAuthNotConfigured(
                "User refresh token missing. Run `firefinds ebay-oauth-url`, "
                "complete consent, then `firefinds ebay-oauth-exchange --code ...`."
            )
        payload = self._post_token_form(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "scope": " ".join(SELL_USER_SCOPES),
            }
        )
        access = payload.get("access_token")
        if not access:
            raise RuntimeError("eBay refresh response missing access_token")
        # eBay may rotate the refresh token — persist if present.
        new_refresh = payload.get("refresh_token")
        if new_refresh:
            self._store_refresh_token(str(new_refresh))
        expires_in = int(payload.get("expires_in") or 7200)
        self._user_access_token = str(access)
        self._user_access_token_expires_at = time.time() + max(60, expires_in - 60)
        return self._user_access_token

    def get_user_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a usable Sell user access token (refresh as needed)."""
        now = time.time()
        if (
            not force_refresh
            and self._user_access_token
            and now < self._user_access_token_expires_at
        ):
            return self._user_access_token
        return self.refresh_user_token()

    def get_user_token_placeholder(self) -> str:
        """Compatibility alias — returns a real user access token when configured."""
        return self.get_user_access_token()

    def user_token_status(self) -> dict[str, Any]:
        """Secrets-free presence status for CLI ebay-user-token-status."""
        path = self._refresh_token_path()
        present = self.user_refresh_token_present()
        mode = None
        if path.is_file():
            try:
                mode = oct(path.stat().st_mode & 0o777)
            except OSError:
                mode = None
        return {
            "ebay_env": self.settings.ebay_env,
            "runame_configured": bool(self._resolve_runame()),
            "refresh_token_present": present,
            "refresh_token_path": str(path),
            "refresh_token_file_mode": mode,
            "access_token_cached": bool(self._user_access_token),
            "scopes": list(SELL_USER_SCOPES),
            "note": (
                "Presence only — token values are never printed. "
                "Sandbox inventory/offer OK with refresh token; publish gated by "
                "EBAY_SANDBOX_PUBLISH_ENABLED."
            ),
        }

    # --- Sell Inventory / Offer (user token) ------------------------------

    def _user_auth_headers(self) -> dict[str, str]:
        token = self.get_user_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-CA",
            "X-EBAY-C-MARKETPLACE-ID": self.settings.ebay_marketplace_id,
        }

    @staticmethod
    def _parse_ebay_errors(body: bytes | str | None) -> list[dict[str, Any]]:
        if not body:
            return []
        try:
            if isinstance(body, bytes):
                text = body.decode("utf-8", errors="replace")
            else:
                text = body
            payload = json.loads(text)
        except (UnicodeError, json.JSONDecodeError, TypeError):
            return []
        if isinstance(payload, dict):
            errs = payload.get("errors")
            if isinstance(errs, list):
                return [e for e in errs if isinstance(e, dict)]
        return []

    def _raise_sell_http(self, exc: urllib.error.HTTPError, *, op: str) -> None:
        raw = b""
        try:
            raw = exc.read() or b""
        except Exception:
            raw = b""
        errors = self._parse_ebay_errors(raw)
        first = errors[0] if errors else {}
        msg = (
            first.get("longMessage")
            or first.get("message")
            or f"eBay Sell {op} failed: HTTP {exc.code}"
        )
        # Never include raw body (may echo tokens); message fields are API text.
        raise EbayApiError(
            str(msg)[:500],
            status=int(exc.code),
            error_id=first.get("errorId"),
            error_name=first.get("errorName") or first.get("category"),
            raw_errors=errors,
        ) from None

    def _sell_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        op: str = "request",
        retry_401: bool = True,
        read_attempt: int = 0,
    ) -> dict[str, Any] | None:
        """Authenticated Sell API call. Returns parsed JSON or None for empty 204."""
        url = f"{self._sell_base()}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        headers = self._user_auth_headers()
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read() or b""
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and retry_401:
                self._user_access_token = None
                self._user_access_token_expires_at = 0.0
                return self._sell_json(
                    method, path, body=body, op=op, retry_401=False,
                    read_attempt=read_attempt
                )
            if method.upper() == "GET":
                from .read_retry import read_retry_delay
                delay = read_retry_delay(exc, read_attempt, max(1, self.settings.retry_max_attempts))
                if delay is not None:
                    exc.close()
                    time.sleep(delay)
                    return self._sell_json(method, path, body=body, op=op,
                                           retry_401=retry_401, read_attempt=read_attempt + 1)
            self._raise_sell_http(exc, op=op)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"eBay Sell {op} failed: {exc.reason}") from None
        return None  # pragma: no cover

    @staticmethod
    def _inventory_body(payload: dict[str, Any]) -> dict[str, Any]:
        """Body for createOrReplaceInventoryItem (sku is path-only)."""
        body = dict(payload)
        body.pop("sku", None)
        # Drop nullish product fields that eBay may reject
        product = body.get("product")
        if isinstance(product, dict):
            cleaned = {k: v for k, v in product.items() if v not in (None, "", [])}
            body["product"] = cleaned
        return body

    def create_or_replace_inventory_item(
        self, sku: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PUT sell/inventory/v1/inventory_item/{sku} with user access token."""
        self._assert_listings_allowed(publish=False)
        sku_clean = str(sku or "").strip()
        if not sku_clean:
            raise ValueError("sku is required")
        body = self._inventory_body(payload if isinstance(payload, dict) else {})
        encoded = urllib.parse.quote(sku_clean, safe="")
        result = self._sell_json(
            "PUT",
            f"/inventory/v1/inventory_item/{encoded}",
            body=body,
            op="createOrReplaceInventoryItem",
        )
        # Success is often HTTP 204 with empty body
        return result if isinstance(result, dict) else {"ok": True, "sku": sku_clean}

    def get_offers_for_sku(self, sku: str) -> dict[str, Any]:
        """GET sell/inventory/v1/offer?sku=..."""
        self._assert_listings_allowed(publish=False)
        sku_clean = str(sku or "").strip()
        qs = urllib.parse.urlencode({"sku": sku_clean})
        result = self._sell_json(
            "GET", f"/inventory/v1/offer?{qs}", op="getOffers"
        )
        return result if isinstance(result, dict) else {"offers": []}

    def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST sell/inventory/v1/offer with user access token."""
        self._assert_listings_allowed(publish=False)
        if not isinstance(payload, dict) or not payload.get("sku"):
            raise ValueError("create_offer requires payload with sku")
        result = self._sell_json(
            "POST", "/inventory/v1/offer", body=payload, op="createOffer"
        )
        return result if isinstance(result, dict) else {"ok": True}

    def update_offer(self, offer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PUT sell/inventory/v1/offer/{offerId}."""
        self._assert_listings_allowed(publish=False)
        oid = str(offer_id or "").strip()
        if not oid:
            raise ValueError("offer_id is required")
        body = dict(payload) if isinstance(payload, dict) else {}
        # offerId is path-only
        body.pop("offerId", None)
        result = self._sell_json(
            "PUT",
            f"/inventory/v1/offer/{urllib.parse.quote(oid, safe='')}",
            body=body,
            op="updateOffer",
        )
        return result if isinstance(result, dict) else {"ok": True, "offerId": oid}

    def create_or_update_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create offer, or update if one already exists for the SKU."""
        self._assert_listings_allowed(publish=False)
        sku = str((payload or {}).get("sku") or "").strip()
        if not sku:
            raise ValueError("offer payload requires sku")
        try:
            existing = self.get_offers_for_sku(sku)
        except EbayApiError:
            existing = {"offers": []}
        offers = existing.get("offers") if isinstance(existing, dict) else None
        if isinstance(offers, list) and offers:
            first = offers[0] if isinstance(offers[0], dict) else {}
            oid = str(first.get("offerId") or "").strip()
            if oid:
                updated = self.update_offer(oid, payload)
                if isinstance(updated, dict):
                    updated = dict(updated)
                    updated.setdefault("offerId", oid)
                    updated["updated"] = True
                    return updated
                return {"offerId": oid, "updated": True}
        created = self.create_offer(payload)
        if isinstance(created, dict):
            created = dict(created)
            created["updated"] = False
        return created

    def publish_offer(self, offer_id: str) -> dict[str, Any]:
        """POST publishOffer — refused unless EBAY_SANDBOX_PUBLISH_ENABLED (sandbox)."""
        self._assert_listings_allowed(publish=True)
        oid = str(offer_id or "").strip()
        if not oid:
            raise ValueError("offer_id is required")
        result = self._sell_json(
            "POST",
            f"/inventory/v1/offer/{urllib.parse.quote(oid, safe='')}/publish",
            body=None,
            op="publishOffer",
        )
        return result if isinstance(result, dict) else {"ok": True, "offerId": oid}

    # --- Sell Fulfillment (paid-order reads + separately gated tracking) ---

    def get_orders(
        self, *, filter_expr: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Read eBay orders through the official Fulfillment API."""
        params = {"limit": str(max(1, min(int(limit), 200))), "offset": str(max(0, int(offset)))}
        if filter_expr:
            params["filter"] = str(filter_expr)
        result = self._sell_json(
            "GET", f"/fulfillment/v1/order?{urllib.parse.urlencode(params)}", op="getOrders"
        )
        return result if isinstance(result, dict) else {"orders": []}

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Read one eBay order; this never mutates buyer or listing state."""
        oid = str(order_id or "").strip()
        if not oid:
            raise ValueError("order_id is required")
        result = self._sell_json(
            "GET", f"/fulfillment/v1/order/{urllib.parse.quote(oid, safe='')}", op="getOrder"
        )
        return result if isinstance(result, dict) else {}

    def list_shipping_fulfillments(self, order_id: str) -> dict[str, Any]:
        """Read tracking fulfillments already recorded for an order."""
        oid = str(order_id or "").strip()
        if not oid:
            raise ValueError("order_id is required")
        result = self._sell_json(
            "GET",
            f"/fulfillment/v1/order/{urllib.parse.quote(oid, safe='')}/shipping_fulfillment",
            op="getShippingFulfillments",
        )
        # A malformed response is not proof that no tracking exists.
        return result if isinstance(result, dict) else {}

    def get_privileges(self) -> dict[str, Any]:
        """Read seller privileges/limits for capacity decisions."""
        result = self._sell_json("GET", "/account/v1/privilege", op="getPrivileges")
        return result if isinstance(result, dict) else {}

    def get_business_policies(self) -> dict[str, dict[str, Any]]:
        """Read existing EBAY_CA policies without creating or changing them."""
        qs = urllib.parse.urlencode({"marketplace_id": self.settings.ebay_marketplace_id})
        out: dict[str, dict[str, Any]] = {}
        for name in ("payment_policy", "return_policy", "fulfillment_policy"):
            result = self._sell_json(
                "GET", f"/account/v1/{name}?{qs}", op=f"get{name.title().replace('_', '')}"
            )
            out[name] = result if isinstance(result, dict) else {}
        return out

    def list_inventory_locations(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Read merchant inventory locations used by Inventory offers."""
        qs = urllib.parse.urlencode({
            "limit": str(max(1, min(int(limit), 100))),
            "offset": str(max(0, int(offset))),
        })
        result = self._sell_json("GET", f"/inventory/v1/location?{qs}", op="getInventoryLocations")
        return result if isinstance(result, dict) else {"locations": []}

    def get_payments_program(self, payments_program_type: str = "EBAY_PAYMENTS") -> dict[str, Any]:
        """Read managed-payments enrollment; never changes financial settings."""
        market = urllib.parse.quote(self.settings.ebay_marketplace_id, safe="")
        program = urllib.parse.quote(str(payments_program_type).strip(), safe="")
        result = self._sell_json(
            "GET", f"/account/v1/payments_program/{market}/{program}", op="getPaymentsProgram"
        )
        return result if isinstance(result, dict) else {}

    def create_shipping_fulfillment(
        self,
        order_id: str,
        *,
        carrier_code: str,
        tracking_number: str,
        line_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Post tracking only when its independent mutation gate is enabled."""
        if (
            self.settings.dry_run
            or self.settings.global_kill_switch
            or not self.settings.ebay_tracking_updates_enabled
        ):
            raise EbayFulfillmentDisabled(
                "Tracking update refused: DRY_RUN/GLOBAL_KILL_SWITCH is active or "
                "EBAY_TRACKING_UPDATES_ENABLED is false"
            )
        if self.settings.ebay_env == "production" and (
            not self.settings.ebay_production_enabled
            or not self.settings.live_listings_enabled
        ):
            raise EbayFulfillmentDisabled(
                "Production fulfillment requires EBAY_PRODUCTION_ENABLED and "
                "LIVE_LISTINGS_ENABLED"
            )
        oid = str(order_id or "").strip()
        carrier = str(carrier_code or "").strip()
        tracking = str(tracking_number or "").strip()
        if not oid or not carrier or not tracking:
            raise ValueError("order_id, carrier_code, and tracking_number are required")
        body: dict[str, Any] = {
            "shippingCarrierCode": carrier,
            "trackingNumber": tracking,
        }
        if line_items:
            body["lineItems"] = line_items
        result = self._sell_json(
            "POST",
            f"/fulfillment/v1/order/{urllib.parse.quote(oid, safe='')}/shipping_fulfillment",
            body=body,
            op="createShippingFulfillment",
        )
        return result if isinstance(result, dict) else {"ok": True, "orderId": oid}

    def sandbox_status(self) -> dict[str, Any]:
        """Safe status dict (no secrets) for CLI ebay-sandbox-status."""
        cid, secret = self._load_credentials()
        return {
            "ebay_env": self.settings.ebay_env,
            "marketplace_id": self.settings.ebay_marketplace_id,
            "live_listings_enabled": self.settings.live_listings_enabled,
            "ebay_production_enabled": self.settings.ebay_production_enabled,
            "ebay_sandbox_publish_enabled": self.settings.ebay_sandbox_publish_enabled,
            "ebay_tracking_updates_enabled": self.settings.ebay_tracking_updates_enabled,
            "ebay_browse_use_production": self.settings.ebay_browse_use_production,
            "credentials_present": bool(cid and secret),
            "client_id_set": bool(cid),
            "client_secret_file_configured": bool(
                self.settings.ebay_client_secret_file
                or os.environ.get("EBAY_CLIENT_SECRET_FILE")
            ),
            "runame_configured": bool(self._resolve_runame()),
            "user_refresh_token_present": self.user_refresh_token_present(),
            "browse_base": self._browse_base(),
            "sell_base": self._sell_base(),
            "listable_export_limit": self.settings.listable_export_limit,
            "note": (
                "Sandbox inventory/offer allowed with user refresh token even when "
                "LIVE_LISTINGS_ENABLED=false. Publish requires "
                "EBAY_SANDBOX_PUBLISH_ENABLED=true. Production Sell requires "
                "EBAY_PRODUCTION_ENABLED + LIVE_LISTINGS_ENABLED."
            ),
        }


# typing alias without importing Mapping at runtime cost for extract helper
