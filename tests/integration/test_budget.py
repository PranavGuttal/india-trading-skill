"""The budget is one number the user changes; every % limit and the paper cash follow it."""
import pytest

from india_trading.brokers.paper_broker import PaperBroker
from india_trading.cli import main
from india_trading.config import ConfigError, Settings, load_settings
from india_trading.models import OrderIntent, Side
from tests.conftest import make_quote


def test_limits_scale_with_the_budget():
    s = Settings(max_experimental_allocation_inr=5000)
    assert s.max_single_order_value_inr == 5000
    assert s.max_risk_per_trade_inr == 50            # 1%
    assert s.daily_loss_limit_inr == 150             # 3%
    assert s.weekly_loss_limit == 300 and s.monthly_loss_limit == 600
    assert s.capital_floor == 4500
    assert s.explicit_limits == []


def test_explicit_rupee_limits_stay_fixed_and_percentages_rescale():
    s = Settings(max_experimental_allocation_inr=5000, max_risk_per_trade_inr=100, risk_per_trade_pct=2)
    t = s.with_budget(20000)
    assert t.max_experimental_allocation_inr == 20000
    assert t.max_risk_per_trade_inr == 100           # explicit ₹ wins
    assert t.max_single_order_value_inr == 20000     # % re-scaled
    assert t.daily_loss_limit_inr == 600
    assert t.explicit_limits == ["max_risk_per_trade_inr"]
    assert Settings(max_experimental_allocation_inr=5000).with_budget(1000).max_risk_per_trade_inr == 10


def test_percent_limits_from_env_and_unsafe_still_rejected():
    s = load_settings(None, env={"MAX_EXPERIMENTAL_ALLOCATION_INR": "10000", "RISK_PER_TRADE_PCT": "0.5"})
    assert s.max_risk_per_trade_inr == 50
    with pytest.raises(ConfigError):
        load_settings(None, env={"RISK_PER_TRADE_PCT": "50"})            # above the 10% ceiling
    with pytest.raises(ConfigError):
        load_settings(None, env={"MAX_EXPERIMENTAL_ALLOCATION_INR": "1000", "MAX_SINGLE_ORDER_VALUE_INR": "5000"})


def test_paper_cash_follows_the_budget(tmp_path, settings):
    db = tmp_path / "paper.db"
    PaperBroker(db, 200, settings.charges)
    b = PaperBroker(db, 5000, settings.charges)
    assert b.cash() == 5000 and b.funded() == 5000 and b.budget_change == (200, 5000)
    b = PaperBroker(db, 1000, settings.charges)
    assert b.cash() == 1000 and b.budget_change == (5000, 1000)
    assert PaperBroker(db, 1000, settings.charges).budget_change is None


def test_budget_cannot_drop_below_money_in_positions(tmp_path, settings):
    db = tmp_path / "paper.db"
    b = PaperBroker(db, 5000, settings.charges, price_provider=lambda s: make_quote(s, 100.0))
    b.place_order(OrderIntent(symbol="ABC", side=Side.BUY, qty=30, limit_price=100, product="delivery",
                              stop=95, target=110, trade_date="2025-09-22", proposal_ref="r"))
    with pytest.raises(ValueError, match="open positions"):
        PaperBroker(db, 1000, settings.charges)
    assert PaperBroker(db, 5000, settings.charges).cash() < 2000          # unchanged by the refused cut


def test_budget_command_sets_and_shows(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAX_EXPERIMENTAL_ALLOCATION_INR", raising=False)
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("state_dir: state\nmax_experimental_allocation_inr: 200   # my budget\nregime_gate: off\n",
                   encoding="utf-8")
    assert main(["--config", str(cfg), "budget"]) == 0
    assert main(["--config", str(cfg), "budget", "set", "7500"]) == 0
    out = capsys.readouterr().out
    assert "₹200.00 → ₹7,500.00" in out and "₹75.00" in out              # risk 1% re-scaled
    text = cfg.read_text(encoding="utf-8")
    assert "max_experimental_allocation_inr: 7500   # my budget" in text and "regime_gate: off" in text
    assert load_settings(cfg, env={}).max_experimental_allocation_inr == 7500
    assert PaperBroker(tmp_path / "state" / "paper.db", 7500, Settings().charges).cash() == 7500
    assert main(["--config", str(cfg), "budget", "set"]) == 2
