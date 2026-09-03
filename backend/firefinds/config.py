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


@dataclass(frozen=True)
class Settings:
    randmar_reseller_id: str = "2WQN9V11G"
    randmar_token_url: str = "https://auth.randmar.io/connect/token"
    randmar_api_base: str = "https://api.randmar.io"
    randmar_client_id: str | None = None
    randmar_client_secret_file: Path | None = DEFAULT_SECRET_FILE
    secrets_dir: Path = DEFAULT_SECRETS_DIR
    live_listings_enabled: bool = False
    supplier_orders_enabled: bool = False
    ebay_production_enabled: bool = False
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
        secrets = os.environ.get("RANDMAR_SECRETS_DIR")
        db = os.environ.get("FIREFINDS_DB_PATH")
        jsonl = os.environ.get("FIREFINDS_ACTIONS_JSONL")
        secret_file = os.environ.get("RANDMAR_CLIENT_SECRET_FILE")
        client_id = os.environ.get("RANDMAR_CLIENT_ID")
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
            randmar_client_id=client_id or None,
            randmar_client_secret_file=(
                Path(secret_file) if secret_file else DEFAULT_SECRET_FILE
            ),
            secrets_dir=Path(secrets) if secrets else DEFAULT_SECRETS_DIR,
            live_listings_enabled=_env_bool("LIVE_LISTINGS_ENABLED", False),
            supplier_orders_enabled=_env_bool("SUPPLIER_ORDERS_ENABLED", False),
            ebay_production_enabled=_env_bool("EBAY_PRODUCTION_ENABLED", False),
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
