"""Configuration with fail-safe defaults.

Precedence: built-in defaults < YAML file < environment variables.
Live trading needs THREE independent switches (mode, flag, and a local
acknowledgement phrase) and is still blocked by the execution layer unless a
verified live broker adapter exists. In this release none does.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

LIVE_ACK_PHRASE = "I understand live orders can lose real money"


class ConfigError(ValueError):
    pass


class ChargeSchedule(BaseModel):
    """Broker + statutory charges. Values are DATA, not facts baked into code.

    Defaults copied from https://groww.in/pricing on 2026-10-30. Re-verify
    before relying on them; update `as_of` when you do.
    """

    source: str = "https://groww.in/pricing"
    as_of: str = "2026-10-30"
    brokerage_pct: float = 0.001          # 0.1% per executed order
    brokerage_cap_inr: float = 20.0       # whichever is lower of ₹20 / 0.1%
    brokerage_min_inr: float = 5.0        # minimum ₹5
    stt_delivery_pct: float = 0.001       # 0.1% buy and sell
    stt_intraday_sell_pct: float = 0.00025  # 0.025% sell side
    stamp_delivery_buy_pct: float = 0.00015
    stamp_intraday_buy_pct: float = 0.00003
    exchange_txn_pct_nse: float = 0.0000297
    sebi_turnover_pct: float = 0.000001
    ipft_pct_nse: float = 0.000001
    gst_pct: float = 0.18
    dp_charge_depository_inr: float = 3.5   # per delivery sell (scrip, per day)
    dp_charge_broker_inr: float = 16.5
    dp_broker_waiver_below_inr: float = 100.0  # Groww part ₹0 if debit value < ₹100


class Settings(BaseModel):
    trading_mode: Literal["paper", "live"] = "paper"
    live_trading_enabled: bool = False
    live_ack: str = ""

    max_experimental_allocation_inr: float = Field(200.0, gt=0)
    max_single_order_value_inr: float = Field(200.0, gt=0)
    max_open_positions: int = Field(1, ge=1)
    allow_short_selling: bool = False
    allow_derivatives: bool = False
    allow_leverage: bool = False
    require_human_approval: bool = True

    product: Literal["delivery", "intraday"] = "delivery"
    max_risk_per_trade_inr: float = Field(10.0, gt=0)
    daily_loss_limit_inr: float = Field(20.0, gt=0)
    # Circuit breaker: None means 2x / 4x the daily limit.
    weekly_loss_limit_inr: Optional[float] = Field(None, gt=0)
    monthly_loss_limit_inr: Optional[float] = Field(None, gt=0)
    max_consecutive_losses: int = Field(3, ge=1)
    loss_cooldown_days: int = Field(2, ge=0)          # business days paused after that streak
    max_trades_per_day: int = Field(2, ge=1)
    min_reward_risk: float = Field(1.5, gt=0)
    # Planned reward must exceed round-trip costs by this multiple.
    min_reward_to_cost: float = Field(2.0, gt=0)
    min_price_inr: float = Field(20.0, gt=0)          # penny-stock floor
    max_quote_age_seconds: int = Field(120, ge=1)
    max_bar_age_days: int = Field(5, ge=1)            # for daily-bar research
    slippage_bps: float = Field(10.0, ge=0)
    # Market gate for NEW entries (exits are never gated):
    #   "index"     no entries while Nifty 50 <= its 200-day average (tested: fewer losses); fails closed
    #               without fresh Nifty data. Default.
    #   "watchlist" no entries while the watchlist's own breadth is RISK_OFF (autopilot only, untested)
    #   "off"       no gate.   (true/false from older settings files mean "index"/"off")
    regime_gate: Literal["index", "watchlist", "off"] = "index"
    # Capital floor, % of the allocation. A new trade must keep equity (open positions
    # valued at their stops) above it even if it hits its own stop; if equity is ever
    # found below it, the autopilot sells everything and engages the kill switch. 0 = off.
    capital_floor_pct: float = Field(90.0, ge=0, lt=100)
    # Signal strategy used by analyze/scan/autopilot/live (see `strategies`).
    # Default = the least-losing swing strategy in the lab on both universes (docs/STRATEGY_LAB.md).
    strategy: str = "trend_template"

    # Live graduation: minimums can only be raised, never lowered below these floors.
    graduation_min_trades: int = Field(30, ge=30)
    graduation_min_days: int = Field(20, ge=20)
    live_approval_ttl_seconds: int = Field(300, ge=30, le=300)   # an approval expires after this

    data_dir: str = "data"
    indices_dir: str = "data/indices"     # Nifty 50, India VIX, sector indices (data-fetch --indices)
    etf_dir: str = "data/etf"             # index ETFs (data-fetch --etf)
    universes_dir: str = "data/universes" # official index lists (universe-fetch NIFTY500)
    state_dir: str = "state"
    watchlist: list[str] = Field(default_factory=lambda: ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC"])
    charges: ChargeSchedule = Field(default_factory=ChargeSchedule)

    @field_validator("regime_gate", mode="before")
    @classmethod
    def _gate_compat(cls, v):
        if isinstance(v, bool):
            return "index" if v else "off"
        return v

    @model_validator(mode="after")
    def _safety(self) -> "Settings":
        if self.allow_short_selling or self.allow_derivatives or self.allow_leverage:
            raise ValueError("short selling, derivatives and leverage are not supported in this release")
        if self.max_single_order_value_inr > self.max_experimental_allocation_inr:
            raise ValueError("max_single_order_value_inr cannot exceed max_experimental_allocation_inr")
        if self.daily_loss_limit_inr > self.max_experimental_allocation_inr:
            raise ValueError("daily_loss_limit_inr cannot exceed the experimental allocation")
        if self.trading_mode == "live" and not self.require_human_approval:
            raise ValueError("live mode requires require_human_approval=true")
        return self

    @property
    def capital_floor(self) -> float:
        return round(self.max_experimental_allocation_inr * self.capital_floor_pct / 100, 2)

    @property
    def weekly_loss_limit(self) -> float:
        return self.weekly_loss_limit_inr or 2 * self.daily_loss_limit_inr

    @property
    def monthly_loss_limit(self) -> float:
        return self.monthly_loss_limit_inr or 4 * self.daily_loss_limit_inr

    @property
    def live_requested(self) -> bool:
        """True only when every live switch is set. Execution still refuses
        without a verified live adapter."""
        return (
            self.trading_mode == "live"
            and self.live_trading_enabled
            and self.live_ack.strip() == LIVE_ACK_PHRASE
        )

    def state_path(self, name: str) -> Path:
        p = Path(self.state_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p / name


_ENV_MAP = {
    "TRADING_MODE": ("trading_mode", str),
    "LIVE_TRADING_ENABLED": ("live_trading_enabled", "bool"),
    "LIVE_TRADING_ACK": ("live_ack", str),
    "MAX_EXPERIMENTAL_ALLOCATION_INR": ("max_experimental_allocation_inr", float),
    "MAX_SINGLE_ORDER_VALUE_INR": ("max_single_order_value_inr", float),
    "MAX_OPEN_POSITIONS": ("max_open_positions", int),
    "ALLOW_SHORT_SELLING": ("allow_short_selling", "bool"),
    "ALLOW_DERIVATIVES": ("allow_derivatives", "bool"),
    "ALLOW_LEVERAGE": ("allow_leverage", "bool"),
    "REQUIRE_HUMAN_APPROVAL": ("require_human_approval", "bool"),
    "INDIA_TRADING_STATE_DIR": ("state_dir", str),
    "INDIA_TRADING_DATA_DIR": ("data_dir", str),
    "CAPITAL_FLOOR_PCT": ("capital_floor_pct", float),
}


def _to_bool(v: str) -> bool:
    s = v.strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off", ""}:
        return False
    raise ConfigError(f"not a boolean: {v!r}")


def load_settings(path: str | Path | None = None, env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)
    data: dict = {}
    path = path or env.get("INDIA_TRADING_CONFIG")
    if path and Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must contain a mapping")
    for key, (field, kind) in _ENV_MAP.items():
        if key in env:
            raw = env[key]
            data[field] = _to_bool(raw) if kind == "bool" else kind(raw)
    try:
        return Settings(**data)
    except ValidationError as e:
        raise ConfigError(f"invalid configuration: {e}") from e
