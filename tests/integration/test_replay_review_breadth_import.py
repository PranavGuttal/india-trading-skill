import pandas as pd
import pytest

from india_trading.analysis.breadth import compute as compute_breadth
from india_trading.cli import main
from india_trading.journal.review import format_review, review
from india_trading.market_data.csv_source import DataError
from india_trading.market_data.importer import import_csv, normalise
from india_trading.simulation.replay import format_replay, run_replay
from tests.conftest import trend_df
from tests.integration.test_backtest_and_workflow import synthetic


def _data(tmp_path, n=260):
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        synthetic(n, seed=20 + i).assign(source="SYNTHETIC").to_csv(d / f"{sym}.csv", index=False)
    return d


def test_replay_runs_day_by_day_in_its_own_state(tmp_path, big_settings):
    d = _data(tmp_path)
    s = big_settings.model_copy(update={"watchlist": ["AAA", "BBB", "CCC"], "max_open_positions": 2})
    out = tmp_path / "replay"
    r = run_replay(s, d, None, None, out)
    assert r.days == 260 and len(r.equity) == 260
    assert (out / "trades.csv").exists() and (out / "equity.csv").exists()
    assert not (tmp_path / "state" / "paper.db").exists()        # real paper state untouched
    m = r.metrics()
    assert m["trades"] == len(r.trades)
    assert m["net_pnl"] == pytest.approx(sum(t["pnl_net"] for t in r.trades), abs=0.05)
    assert "VERDICT" in format_replay(r) and "SYNTHETIC" in format_replay(r)
    again = run_replay(s, d, None, None, out)
    assert again.metrics() == m                                   # deterministic, state reset


def test_replay_at_200_budget_trades_nothing(tmp_path, settings):
    d = _data(tmp_path)
    s = settings.model_copy(update={"watchlist": ["AAA", "BBB", "CCC"]})
    r = run_replay(s, d, None, None, tmp_path / "replay")
    assert r.metrics()["trades"] == 0 and r.verdict().startswith("INCONCLUSIVE")


def test_review_numbers():
    closed = [dict(pnl_net=10.0, charges=2.0, reason="autopilot-exit:target:x"),
              dict(pnl_net=-5.0, charges=2.0, reason="autopilot-exit:stop:x"),
              dict(pnl_net=-4.0, charges=2.0, reason="manual-exit:2025-01-01T10:00")]
    events = [{"kind": "RISK_BLOCKED", "summary": "kill switch is engaged", "intent_id": None},
              {"kind": "ORDER_SUBMITTED", "summary": "", "intent_id": "a"},
              {"kind": "APPROVED", "summary": "", "intent_id": "a"}]
    r = review(closed, events)
    assert r["closed_trades"] == 3 and r["net_pnl"] == 1.0 and r["charges"] == 6.0
    assert r["worst_losing_streak"] == 2 and r["exit_reasons"] == {"target": 1, "stop": 1, "manual": 1}
    assert r["orders_without_approval_event"] == 0 and r["top_block_reasons"] == {"kill switch is engaged": 1}
    assert "TOO EARLY" in format_review(r)


def test_breadth_regimes():
    up = {f"U{i}": trend_df(260, step=0.4, seed=i) for i in range(5)}
    down = {f"D{i}": trend_df(260, start=300, step=-0.4, seed=i) for i in range(5)}
    assert compute_breadth(up).regime == "RISK_ON"
    assert compute_breadth(down).regime == "RISK_OFF"
    b = compute_breadth({"U0": up["U0"]})
    assert any("noisy" in n for n in b.notes)


def test_import_nse_style_export(tmp_path):
    raw = pd.DataFrame({
        "Date ": ["03-Jan-2024", "02-Jan-2024", "02-Jan-2024", "04-Jan-2024"],
        "series ": ["EQ", "EQ", "EQ", "BE"],
        "OPEN ": ["1,500.00", "1,490.00", "1,490.00", "1,600"],
        "HIGH ": ["1,520.00", "1,505.00", "1,505.00", "1,610"],
        "LOW ": ["1,495.00", "1,480.00", "1,480.00", "1,590"],
        "close ": ["1,510.00", "1,500.00", "1,500.00", "1,605"],
        "VOLUME ": ["1,00,000", "90,000", "90,000", "5"],
    })
    src = tmp_path / "export.csv"
    raw.to_csv(src, index=False)
    out, _ = import_csv(src, "infy", tmp_path / "real", "nse-historical")
    df = pd.read_csv(out)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "source"]
    assert list(df["date"]) == ["2024-01-02", "2024-01-03"]       # sorted, de-duplicated, EQ only
    assert df["volume"].iloc[1] == 100000 and (df["source"] == "nse-historical").all()


def test_import_refuses_missing_columns_and_bad_rows(tmp_path):
    with pytest.raises(DataError):
        normalise(pd.DataFrame({"date": ["2024-01-02"], "open": [1]}), "x")
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"date": ["2024-01-02"], "open": [10], "high": [5], "low": [4], "close": [9],
                  "volume": [1]}).to_csv(bad, index=False)
    with pytest.raises(DataError):
        import_csv(bad, "X", tmp_path / "real", "x")


def test_cli_new_commands_run(tmp_path, capsys, monkeypatch):
    d = _data(tmp_path)
    cfg = tmp_path / "s.yaml"
    cfg.write_text(f"data_dir: {d.as_posix()}\nstate_dir: {(tmp_path / 'st').as_posix()}\n"
                   "watchlist: [AAA, BBB, CCC]\n", encoding="utf-8")
    base = ["--config", str(cfg)]
    assert main(base + ["costs", "200"]) == 0
    assert "Round trip" in capsys.readouterr().out
    assert main(base + ["breadth"]) == 0
    assert main(base + ["timemachine", "AAA", "--entry", "150", "--stop", "140", "--target", "170", "--paths", "500"]) in (0, 2)
    assert main(base + ["autopilot"]) == 0
    assert "AUTOPILOT TICK" in capsys.readouterr().out
    assert main(base + ["review"]) == 0
    assert main(base + ["replay", "--capital", "20000", "--risk", "200", "--start", "2023-06-01"]) == 0
    assert "REPLAY" in capsys.readouterr().out
