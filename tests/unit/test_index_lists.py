from pathlib import Path

import pytest

from india_trading.cli import _universe
from india_trading.market_data import index_lists as il
from india_trading.market_data.csv_source import DataError

RAW = (Path(__file__).parent.parent / "fixtures" / "ind_nifty500list_head.csv").read_bytes()   # real NSE file, first rows


def test_fetch_saves_official_list_with_provenance(tmp_path):
    seen = []
    p, df = il.fetch("nifty500", tmp_path, http_get=lambda u: (seen.append(u), RAW)[1])
    assert "niftyindices.com" in seen[0] and seen[0].endswith("ind_nifty500list.csv")
    assert p.name == "NIFTY500.csv" and len(df) == 5
    assert {"Symbol", "Industry", "source_url", "fetched"} <= set(il.load("NIFTY500", tmp_path).columns)


def test_retry_once_then_clear_error(tmp_path):
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("timed out")
        return RAW
    il.fetch("NIFTY500", tmp_path, http_get=flaky)
    assert len(calls) == 2
    with pytest.raises(DataError, match="download failed"):
        il.fetch("NIFTY500", tmp_path, http_get=lambda u: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(DataError, match="unknown index list"):
        il.fetch("NIFTY9999", tmp_path)
    with pytest.raises(DataError, match="unexpected columns"):
        il.fetch("NIFTY500", tmp_path, http_get=lambda u: b"a,b\n1,2\n")


def test_official_industries_feed_the_sector_map_and_universes(tmp_path, monkeypatch):
    il.fetch("NIFTY500", tmp_path / "u", http_get=lambda u: RAW)
    m = il.official_sector_map(tmp_path / "u")
    assert m["ABB"] == {"sector": "Capital Goods", "index": "NIFTYINFRA"}
    assert m["360ONE"]["index"] == "NIFTYFINSERV"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "u").rename(tmp_path / "data" / "universes")
    assert _universe("NIFTY500")[:2] == ["360ONE", "ABB"]
    with pytest.raises(KeyError, match="universe-fetch"):
        _universe("NIFTYMIDCAP150")
