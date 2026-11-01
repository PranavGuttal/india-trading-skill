import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from india_trading.market_data.calendar import IST
from india_trading.market_data.csv_source import DataError, load_csv
from india_trading.market_data.yahoo_source import SOURCE, fetch, fetch_to_csv, parse_chart

FIXTURE = Path(__file__).parent.parent / "fixtures" / "yahoo_INFY_NS.json"   # recorded real response, trimmed


def payload():
    return json.loads(FIXTURE.read_text())


def test_parses_recorded_nse_response():
    df = parse_chart(payload(), "INFY", now=datetime(2030, 1, 1, tzinfo=IST))
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "source"]
    assert len(df) == 80 and df["date"].is_monotonic_increasing and not df["date"].duplicated().any()
    assert (df["source"] == SOURCE).all()
    assert (df["high"] >= df[["open", "close"]].max(axis=1)).all()


def test_drops_unfinished_bar_during_session():
    p = payload()
    last = pd.to_datetime(p["chart"]["result"][0]["timestamp"][-1], unit="s", utc=True).tz_convert(IST)
    during = datetime.combine(last.date(), datetime.min.time().replace(hour=11), tzinfo=IST)
    after = datetime.combine(last.date(), datetime.min.time().replace(hour=16), tzinfo=IST)
    assert len(parse_chart(p, "INFY", now=during)) == 79
    assert len(parse_chart(p, "INFY", now=after)) == 80


def test_errors_and_non_nse_listing_are_refused():
    with pytest.raises(DataError):
        parse_chart({"chart": {"result": None, "error": {"description": "No data found"}}}, "NOPE")
    p = payload()
    p["chart"]["result"][0]["meta"]["exchangeName"] = "NMS"
    with pytest.raises(DataError):
        parse_chart(p, "INFY")
    with pytest.raises(DataError):
        fetch("INFY; rm -rf", http_get=lambda u: b"{}")


def test_fetch_to_csv_writes_loadable_file_without_network(tmp_path):
    seen = []
    res = fetch_to_csv(["infy"], tmp_path, http_get=lambda u: (seen.append(u), json.dumps(payload()).encode())[1],
                       pause_s=0)
    assert res[0][1] == "OK" and "INFY.NS" in seen[0]
    df, rep, src = load_csv(tmp_path / "INFY.csv", "INFY")
    assert rep.ok and "yahoo" in src and "SYNTHETIC" not in src
    bad = fetch_to_csv(["XX"], tmp_path, http_get=lambda u: (_ for _ in ()).throw(OSError("offline")), pause_s=0)
    assert bad[0][1] == "ERROR" and "offline" in bad[0][2][0]
