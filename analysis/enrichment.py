"""
Enriches holdings with sector, industry, country, and performance data via yfinance.
Skips enrichment for CASH / money-market symbols gracefully.
"""

import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from brokerage.base import Holding

SKIP_ASSET_TYPES = {"CASH"}
CASH_LIKE_SYMBOLS = {"SPAXX", "FDRXX", "FCASH", "MMDA1", "SWVXX", "SNSXX"}

_PERIOD_MAP = {
    "1mo": "perf_1m",
    "3mo": "perf_3m",
    "ytd": "perf_ytd",
    "1y": "perf_1y",
}


def _pct_change(series) -> float | None:
    if series is None or len(series) < 2:
        return None
    first = series.iloc[0]
    last = series.iloc[-1]
    if first and first != 0:
        return round((last / first - 1) * 100, 2)
    return None


def _enrich_one(holding: Holding) -> Holding:
    if holding.asset_type in SKIP_ASSET_TYPES or holding.symbol in CASH_LIKE_SYMBOLS:
        holding.sector = "Cash & Equivalents"
        holding.country = "N/A"
        return holding

    try:
        ticker = yf.Ticker(holding.symbol)
        info = ticker.info or {}

        holding.sector = info.get("sector") or _infer_sector(info)
        holding.industry = info.get("industry")
        holding.country = info.get("country", "United States")

        # Historical performance
        for period, attr in _PERIOD_MAP.items():
            try:
                hist = ticker.history(period=period)
                setattr(holding, attr, _pct_change(hist["Close"]) if not hist.empty else None)
            except Exception:
                pass

    except Exception:
        pass

    return holding


def _infer_sector(info: dict) -> str:
    """Fallback sector inference from fund category or quote type."""
    qt = info.get("quoteType", "")
    cat = info.get("category", "")
    if "BOND" in qt.upper() or "FIXED" in cat.upper() or "BOND" in cat.upper():
        return "Fixed Income"
    if "ETF" in qt.upper():
        return "Diversified"
    if "MUTUALFUND" in qt.upper():
        return "Diversified"
    return "Unknown"


def enrich_holdings(holdings: list[Holding], max_workers: int = 8) -> list[Holding]:
    """Parallel yfinance enrichment for all holdings."""
    unique_symbols = {h.symbol for h in holdings}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_enrich_one, h): h for h in holdings}
        enriched = [f.result() for f in as_completed(futures)]

    return enriched
