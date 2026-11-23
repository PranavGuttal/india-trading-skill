"""data-fetch must download the stocks of --universe even when --indices/--etf are also given."""
import pytest

from india_trading import cli


@pytest.fixture
def calls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    seen = []

    def fake(syms, out, years, cal):
        seen.append((list(syms), str(out)))
        return [(s, "OK", []) for s in syms]

    monkeypatch.setattr(cli, "fetch_to_csv", fake)
    return seen


def test_universe_with_indices_and_etf_fetches_all_three(calls):
    assert cli.main(["data-fetch", "--universe", "large_caps_20", "--indices", "--etf", "--out", "data/real"]) == 0
    assert len(calls) == 3
    assert "INFY" in calls[0][0] and calls[0][1] == "data/real"
    assert "NIFTY50" in calls[1][0] and "NIFTYBEES" in calls[2][0]


def test_indices_alone_fetches_only_indices(calls):
    assert cli.main(["data-fetch", "--indices"]) == 0
    assert len(calls) == 1 and "NIFTY50" in calls[0][0]
