"""Every command end to end in a FRESH project folder (no config/ there), the
way the installed plugin runs inside a user's project. Synthetic data only."""
import json

import pytest

from india_trading.cli import main
from tests.helpers import walk, write


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("INDIA_TRADING_DATA_DIR", "INDIA_TRADING_STATE_DIR", "INDIA_TRADING_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    syms = ["AAA", "BBB", "CCC", "DDD"]
    for i, s in enumerate(syms):
        write(walk(520, drift=0.0006 * (i - 1), vol=0.014, seed=20 + i), tmp_path / "data", s)
    (tmp_path / "data" / "events").mkdir()
    (tmp_path / "data" / "events" / "AAA.json").write_text(json.dumps(
        {"symbol": "AAA", "events": [{"date": "2023-06-01", "type": "dividend", "amount": 2.0}]}), encoding="utf-8")
    write(walk(520, drift=0.0005, vol=0.008, seed=30), tmp_path / "data" / "indices", "NIFTY50")
    write(walk(520, start=15, drift=0, vol=0.03, seed=31), tmp_path / "data" / "indices", "INDIAVIX")
    write(walk(520, drift=0.001, vol=0.01, seed=32), tmp_path / "data" / "indices", "NIFTYIT")
    write(walk(520, start=250, drift=0.0005, vol=0.008, seed=33), tmp_path / "data" / "etf", "NIFTYBEES")
    (tmp_path / "settings.yaml").write_text(
        "data_dir: data\nstate_dir: state\nwatchlist: [AAA, BBB]\n"
        "max_experimental_allocation_inr: 50000\nmax_single_order_value_inr: 20000\n"
        "max_risk_per_trade_inr: 500\ndaily_loss_limit_inr: 1500\n", encoding="utf-8")
    (tmp_path / "h.csv").write_text("symbol,qty,avg_price\nAAA,10,90\nBBB,5,120\n", encoding="utf-8")
    (tmp_path / "alerts.yaml").write_text("alerts:\n  - {symbol: AAA, above: 1}\n", encoding="utf-8")
    return tmp_path


COMMANDS = [
    ["status"], ["strategies"], ["doctor"], ["regime"], ["sectors"], ["screen"], ["screen", "--setup", "near_high"],
    ["technical", "AAA"], ["size", "100", "95", "--risk", "500", "--budget", "10000"],
    ["plan", "AAA", "--entry", "100", "--stop", "95", "--target", "112", "--risk", "500", "--budget", "10000"],
    ["exit-plan"], ["portfolio", "--holdings", "h.csv"], ["alerts", "--file", "alerts.yaml"], ["actions", "AAA"],
    ["allocate"], ["allocate", "--paper", "--force"], ["allocate", "--strategy-name", "momentum_rotation"],
    ["scan", "--strategy", "donchian_trend"], ["analyze", "AAA", "--strategy", "rsi2_reversion"],
    ["backtest", "AAA", "--strategy", "trend_template", "--capital", "20000", "--risk", "200"],
    ["lab", "--strategies", "donchian_trend,etf_trend", "--capital", "50000"],
    ["autopilot", "--strategy", "donchian_trend"], ["costs", "500", "--qty", "10"], ["risk-status"], ["review"],
    ["daily", "--paper", "--out", "reports"], ["live", "status"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: " ".join(a))
def test_command_runs(project, argv, capsys):
    code = main(["--config", "settings.yaml"] + argv)
    out = capsys.readouterr()
    assert "Traceback" not in out.out + out.err
    assert code in (0, 1), out.out + out.err                 # 1 = ran fine but found something to report
    assert out.out.strip()


def test_unknown_strategy_is_a_clear_error(project, capsys):
    assert main(["--config", "settings.yaml", "scan", "--strategy", "nope"]) == 2
    assert "unknown signal strategy" in capsys.readouterr().err


def test_daily_writes_a_report(project):
    main(["--config", "settings.yaml", "daily", "--out", "reports"])
    files = list((project / "reports").glob("*.md"))
    assert files and "Market regime" in files[0].read_text(encoding="utf-8")
