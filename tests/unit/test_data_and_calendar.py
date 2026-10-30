from datetime import date, datetime

import pandas as pd
import pytest

from india_trading.market_data.calendar import IST, NSECalendar
from india_trading.market_data.csv_source import DataError, is_stale, load_csv, validate_bars
from tests.conftest import trend_df


def test_valid_data_passes():
    assert validate_bars(trend_df(80)).ok


@pytest.mark.parametrize("mutate,err", [
    (lambda d: d.drop(columns=["volume"]), "missing columns"),
    (lambda d: pd.concat([d, d.iloc[[-1]]]), "duplicate dates"),
    (lambda d: d.iloc[::-1], "not in increasing order"),
    (lambda d: d.assign(close=d["close"].where(d.index != 5)), "missing values"),
    (lambda d: d.assign(low=d["low"].where(d.index != 5, -1)), "non-positive"),
    (lambda d: d.assign(high=d["high"].where(d.index != 7, 1.0)), "high/low"),
])
def test_bad_data_detected(mutate, err):
    rep = validate_bars(mutate(trend_df(80)))
    assert not rep.ok and any(err in e for e in rep.errors)


def test_split_like_jump_warns():
    df = trend_df(80)
    df.loc[40:, ["open", "high", "low", "close"]] /= 2
    rep = validate_bars(df)
    assert rep.ok and any("one-day moves" in w for w in rep.warnings)


def test_load_csv_missing_file(tmp_path):
    with pytest.raises(DataError):
        load_csv(tmp_path / "NOPE.csv")


def test_load_csv_labels_source(tmp_path):
    df = trend_df(70)
    df["source"] = "SYNTHETIC"
    p = tmp_path / "ABC.csv"
    df.to_csv(p, index=False)
    out, rep, src = load_csv(p)
    assert rep.ok and "SYNTHETIC" in src and "source" not in out.columns


def test_staleness():
    df = trend_df(70)  # ends ~ 2024-04
    assert is_stale(df, date(2025, 1, 1), 5)
    assert not is_stale(df, pd.Timestamp(df["date"].iloc[-1]).date(), 5)


def test_calendar_session_and_holidays():
    cal = NSECalendar({2025: {date(2025, 10, 2)}})
    assert cal.status(datetime(2025, 9, 22, 11, 0, tzinfo=IST)).is_open
    assert not cal.status(datetime(2025, 9, 22, 9, 0, tzinfo=IST)).is_open
    assert not cal.status(datetime(2025, 9, 22, 15, 30, tzinfo=IST)).is_open
    assert not cal.status(datetime(2025, 9, 20, 11, 0, tzinfo=IST)).is_open   # Saturday
    s = cal.status(datetime(2025, 10, 2, 11, 0, tzinfo=IST))
    assert not s.is_open and s.reason == "NSE holiday"
    assert not NSECalendar().status(datetime(2025, 9, 22, 11, 0, tzinfo=IST)).holidays_verified


def test_calendar_rejects_naive_time():
    with pytest.raises(ValueError):
        NSECalendar().status(datetime(2025, 9, 22, 11, 0))
