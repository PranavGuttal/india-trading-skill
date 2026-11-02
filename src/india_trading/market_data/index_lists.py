"""Official NSE index constituent lists (NSE Indices Ltd, niftyindices.com).

Verified 2026-11-02: the CSV files download directly and contain Company
Name, Industry (NSE's own classification), Symbol, Series and ISIN. Saved to
data/universes/<NAME>.csv with the source URL and download date, so a
universe is always traceable. Constituents change at each semi-annual
review: re-download before relying on a list, and remember a backtest on
today's list has survivorship bias.
"""
from __future__ import annotations

import io
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from .calendar import IST
from .csv_source import DataError

BASE = "https://www.niftyindices.com/IndexConstituent/{file}"
LISTS = {
    "NIFTY50": "ind_nifty50list.csv",
    "NIFTYNEXT50": "ind_niftynext50list.csv",
    "NIFTY100": "ind_nifty100list.csv",
    "NIFTY200": "ind_nifty200list.csv",
    "NIFTY500": "ind_nifty500list.csv",
    "NIFTYMIDCAP150": "ind_niftymidcap150list.csv",
    "NIFTYSMALLCAP250": "ind_niftysmallcap250list.csv",
}
# NSE industry -> Nifty sector index used for relative strength (closest broad index).
INDUSTRY_INDEX = {
    "Financial Services": "NIFTYFINSERV", "Information Technology": "NIFTYIT", "Healthcare": "NIFTYPHARMA",
    "Fast Moving Consumer Goods": "NIFTYFMCG", "Automobile and Auto Components": "NIFTYAUTO",
    "Metals & Mining": "NIFTYMETAL", "Oil Gas & Consumable Fuels": "NIFTYENERGY", "Power": "NIFTYENERGY",
    "Realty": "NIFTYREALTY", "Construction": "NIFTYINFRA", "Construction Materials": "NIFTYINFRA",
    "Capital Goods": "NIFTYINFRA", "Telecommunication": "NIFTYINFRA", "Services": "NIFTYINFRA",
    "Consumer Durables": "NIFTYCONSUMPTION", "Consumer Services": "NIFTYCONSUMPTION",
    "Chemicals": None, "Textiles": None, "Media Entertainment & Publication": None, "Diversified": None,
    "Forest Materials": None,
}
_UA = "Mozilla/5.0 (india-trading-skill; personal research)"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as r:          # noqa: S310 (fixed https host)
        return r.read()


def parse(raw: bytes, name: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip() for c in df.columns]
    need = {"Symbol", "Industry", "Series"}
    if not need <= set(df.columns):
        raise DataError(f"{name}: unexpected columns {list(df.columns)} (the official file format changed?)")
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    if df["Symbol"].duplicated().any() or df.empty:
        raise DataError(f"{name}: empty list or duplicate symbols")
    return df


def fetch(name: str, out_dir: str | Path = "data/universes", http_get: Callable[[str], bytes] = _get,
          now: Optional[datetime] = None) -> tuple[Path, pd.DataFrame]:
    key = name.upper().replace(" ", "").replace("_", "")
    if key not in LISTS:
        raise DataError(f"unknown index list {name!r}; choose {', '.join(LISTS)}")
    url = BASE.format(file=LISTS[key])
    last = None
    for _ in range(2):                                   # one retry: the site sometimes times out
        try:
            df = parse(http_get(url), key)
            break
        except DataError:
            raise
        except Exception as e:
            last = e
    else:
        raise DataError(f"download failed for {key}: {last}")
    df["source_url"] = url
    df["fetched"] = (now or datetime.now(IST)).date().isoformat()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{key}.csv"
    df.to_csv(p, index=False)
    return p, df


def load(name: str, folder: str | Path = "data/universes") -> Optional[pd.DataFrame]:
    """The saved list without NSE's placeholder rows (e.g. DUMMYHEG, used around demergers)."""
    p = Path(folder) / f"{name.upper().replace('_', '')}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    return df[~df["Symbol"].astype(str).str.upper().str.startswith("DUMMY")].reset_index(drop=True)


def official_sector_map(folder: str | Path = "data/universes") -> dict[str, dict]:
    """symbol -> {sector (NSE industry), index} from every downloaded list."""
    out: dict[str, dict] = {}
    f = Path(folder)
    if not f.exists():
        return out
    for p in sorted(f.glob("*.csv")):
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        if not {"Symbol", "Industry"} <= set(df.columns):
            continue
        for sym, ind in zip(df["Symbol"].astype(str), df["Industry"].astype(str)):
            out[sym.upper()] = {"sector": ind, "index": INDUSTRY_INDEX.get(ind)}
    return out
