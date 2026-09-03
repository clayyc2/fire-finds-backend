"""Configuration from environment (.env-style) with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SECRETS_DIR = PROJECT_ROOT / "secrets"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "firefinds.db"
DEFAULT_ACTIONS_JSONL = DEFAULT_DATA_DIR / "actions.jsonl"
DEFAULT_SECRET_FILE = DEFAULT_SECRETS_DIR / "randmar_api_key.txt"
# Integration key *name* (not a secret). Used when RANDMAR_CLIENT_ID is unset.
DEFAULT_RANDMAR_CLIENT_ID = "Fire Finds catalog read"
DEFAULT_CLIENT_ID_FILE = DEFAULT_SECRETS_DIR / "randmar_client_id.txt"
DEFAULT_EBAY_SECRET_FILE = DEFAULT_SECRETS_DIR / "ebay_client_secret.txt"


def parse_dotenv_value(raw: str) -> str:
    """Strip optional surrounding single/double quotes from a .env value."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_dotenv_line(line: str) -> tuple[str, str] | None:
    """Parse one .env line into (key, value), or None if not an assignment.

    Supports:
    - KEY=value
    - KEY="quoted value"
    - KEY='quoted value'
    - KEY=unquoted value with spaces
    Comments (# ...) and blank lines are ignored.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].lstrip()
    if "=" not in stripped:
        return None
    key, _, rest = stripped.partition("=")
    key = key.strip()
    if not key:
        return None
    return key, parse_dotenv_value(rest)


def load_dotenv(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    By default does not override variables already set in the environment.
    Returns the key/value pairs that were applied (or would apply if override).
    """
    env_path = path if path is not None else PROJECT_ROOT / ".env"
    applied: dict[str, str] = {}
    if not env_path.is_file():
        return applied
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return applied
    for line in text.splitlines():
        parsed = parse_dotenv_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _resolve_client_id(secrets_dir: Path) -> str:
    """Resolve Randmar client id: env, secrets/randmar_client_id.txt, then default."""
    env_val = os.environ.get("RANDMAR_CLIENT_ID")
    if env_val and env_val.strip():
        return env_val.strip()
    for name in ("randmar_client_id.txt", "client_id", "RANDMAR_CLIENT_ID"):
        path = secrets_dir / name
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text:
                return text
    return DEFAULT_RANDMAR_CLIENT_ID


def _resolve_ebay_client_id(secrets_dir: Path) -> str | None:
    env_val = os.environ.get("EBAY_CLIENT_ID")
    if env_val and env_val.strip():
        return env_val.strip()
    for name in ("ebay_client_id.txt", "EBAY_CLIENT_ID"):
        path = secrets_dir / name
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                text = ""
            if text:
                return text
    return None


@dataclass(frozen=True)
class Settings:
    randmar_reseller_id: str = "2WQN9V11G"
    randmar_token_url: str = "https://auth.randmar.io/connect/token"
    randmar_api_base: str = "https://api.randmar.io"
    randmar_client_id: str | None = DEFAULT_RANDMAR_CLIENT_ID
    randmar_client_secret_file: Path | None = DEFAULT_SECRET_FILE
    secrets_dir: Path = DEFAULT_SECRETS_DIR
    live_listings_enabled: bool = False
    supplier_orders_enabled: bool = False
    ebay_production_enabled: bool = False
    # eBay validation path
    ebay_env: str = "sandbox"  # sandbox | production (Sell default)
    ebay_client_id: str | None = None
    ebay_client_secret_file: Path | None = DEFAULT_EBAY_SECRET_FILE
    ebay_marketplace_id: str = "EBAY_CA"
    ebay_sandbox_publish_enabled: bool = False
    ebay_browse_use_production: bool = True
    ebay_compete_strategy: str = "min_map_median"
    ebay_compete_median_factor: float = 0.98
    ebay_comp_top_n: int = 10
    ebay_min_comp_listings: int = 1
    # Soft export/display limit only — NEVER truncates the ranked queue.
    listable_export_limit: int = 0  # 0 = no limit
    allow_provisional_listable: bool = True
    monthly_demand_baseline: float = 4.0
    # Shipping quotes (final listable requires RESOLVED quote — no flat default)
    ship_quote_enabled: bool = True
    ship_to_name: str = "Fire Finds Estimate"
    ship_to_street1: str = "1 Yonge Street"
    ship_to_street2: str = ""
    ship_to_city: str = "Toronto"
    ship_to_province: str = "ON"
    ship_to_postal_code: str = "M5E1E5"
    ship_to_country: str = "CA"
    # Return-risk
    return_risk_heavy_weight_lb: float = 30.0
    return_risk_high_msrp_cad: float = 1500.0
    min_contribution_profit_cad: float = 8.0
    min_contribution_margin: float = 0.12
    stock_buffer: int = 2
    ebay_fee_rate: float = 0.1325
    ebay_fee_fixed: float = 0.30
    ship_est_cad: float = 10.0
    msrp_discount: float = 0.95
    db_path: Path = DEFAULT_DB_PATH
    actions_jsonl: Path = DEFAULT_ACTIONS_JSONL

    @classmethod
    def from_env(cls) -> "Settings":
        # Auto-load PROJECT_ROOT/.env so CLI works without manual `export` / `. .env`.
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        secrets = os.environ.get("RANDMAR_SECRETS_DIR")
        secrets_dir = Path(secrets) if secrets else DEFAULT_SECRETS_DIR
        db = os.environ.get("FIREFINDS_DB_PATH")
        jsonl = os.environ.get("FIREFINDS_ACTIONS_JSONL")
        secret_file = os.environ.get("RANDMAR_CLIENT_SECRET_FILE")
        ebay_secret_file = os.environ.get("EBAY_CLIENT_SECRET_FILE")
        client_id = _resolve_client_id(secrets_dir)
        ebay_client_id = _resolve_ebay_client_id(secrets_dir)
        ebay_env_raw = (os.environ.get("EBAY_ENV") or "sandbox").strip().lower()
        ebay_env = "production" if ebay_env_raw == "production" else "sandbox"
        strategy = (
            os.environ.get("EBAY_COMPETE_STRATEGY") or "min_map_median"
        ).strip().lower()
        if strategy not in {"min_map_median", "median", "lowest"}:
            strategy = "min_map_median"
        return cls(
            randmar_reseller_id=os.environ.get(
                "RANDMAR_RESELLER_ID", "2WQN9V11G"
            ),
            randmar_token_url=os.environ.get(
                "RANDMAR_TOKEN_URL", "https://auth.randmar.io/connect/token"
            ),
            randmar_api_base=os.environ.get(
                "RANDMAR_API_BASE", "https://api.randmar.io"
            ),
            randmar_client_id=client_id,
            randmar_client_secret_file=(
                Path(secret_file) if secret_file else DEFAULT_SECRET_FILE
            ),
            secrets_dir=secrets_dir,
            live_listings_enabled=_env_bool("LIVE_LISTINGS_ENABLED", False),
            supplier_orders_enabled=_env_bool("SUPPLIER_ORDERS_ENABLED", False),
            ebay_production_enabled=_env_bool("EBAY_PRODUCTION_ENABLED", False),
            ebay_env=ebay_env,
            ebay_client_id=ebay_client_id,
            ebay_client_secret_file=(
                Path(ebay_secret_file)
                if ebay_secret_file
                else DEFAULT_EBAY_SECRET_FILE
            ),
            ebay_marketplace_id=os.environ.get(
                "EBAY_MARKETPLACE_ID", "EBAY_CA"
            ).strip()
            or "EBAY_CA",
            ebay_sandbox_publish_enabled=_env_bool(
                "EBAY_SANDBOX_PUBLISH_ENABLED", False
            ),
            ebay_browse_use_production=_env_bool(
                "EBAY_BROWSE_USE_PRODUCTION", True
            ),
            ebay_compete_strategy=strategy,
            ebay_compete_median_factor=_env_float(
                "EBAY_COMPETE_MEDIAN_FACTOR", 0.98
            ),
            ebay_comp_top_n=_env_int("EBAY_COMP_TOP_N", 10),
            ebay_min_comp_listings=_env_int("EBAY_MIN_COMP_LISTINGS", 1),
            listable_export_limit=_env_int("LISTABLE_EXPORT_LIMIT", 0),
            allow_provisional_listable=_env_bool(
                "ALLOW_PROVISIONAL_LISTABLE", True
            ),
            monthly_demand_baseline=_env_float("MONTHLY_DEMAND_BASELINE", 4.0),
            ship_quote_enabled=_env_bool("SHIP_QUOTE_ENABLED", True),
            ship_to_name=os.environ.get(
                "SHIP_TO_NAME", "Fire Finds Estimate"
            ),
            ship_to_street1=os.environ.get(
                "SHIP_TO_STREET1", "1 Yonge Street"
            ),
            ship_to_street2=os.environ.get("SHIP_TO_STREET2", ""),
            ship_to_city=os.environ.get("SHIP_TO_CITY", "Toronto"),
            ship_to_province=os.environ.get("SHIP_TO_PROVINCE", "ON"),
            ship_to_postal_code=os.environ.get(
                "SHIP_TO_POSTAL_CODE", "M5E1E5"
            ),
            ship_to_country=os.environ.get("SHIP_TO_COUNTRY", "CA"),
            return_risk_heavy_weight_lb=_env_float(
                "RETURN_RISK_HEAVY_WEIGHT_LB", 30.0
            ),
            return_risk_high_msrp_cad=_env_float(
                "RETURN_RISK_HIGH_MSRP_CAD", 1500.0
            ),
            min_contribution_profit_cad=_env_float(
                "MIN_CONTRIBUTION_PROFIT_CAD", 8.0
            ),
            min_contribution_margin=_env_float("MIN_CONTRIBUTION_MARGIN", 0.12),
            stock_buffer=_env_int("STOCK_BUFFER", 2),
            ebay_fee_rate=_env_float("EBAY_FEE_RATE", 0.1325),
            ebay_fee_fixed=_env_float("EBAY_FEE_FIXED", 0.30),
            ship_est_cad=_env_float("SHIP_EST_CAD", 10.0),
            msrp_discount=_env_float("MSRP_DISCOUNT", 0.95),
            db_path=Path(db) if db else DEFAULT_DB_PATH,
            actions_jsonl=Path(jsonl) if jsonl else DEFAULT_ACTIONS_JSONL,
        )


def get_settings() -> Settings:
    return Settings.from_env()
