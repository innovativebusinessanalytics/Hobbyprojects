"""
Enriches holdings with sector, industry, country, and performance data via yfinance.
Skips options, cash, and unresolvable tickers gracefully.
"""

import re
import logging
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from brokerage.base import Holding

log = logging.getLogger(__name__)

# Common money-market / cash symbols at Fidelity and Schwab
CASH_LIKE = {
    # Fidelity
    "SPAXX", "FDRXX", "FCASH", "FZFXX", "FMPXX", "FZDXX", "SPRXX",
    "FTEXX", "FRBXX", "FZAXX", "FDLXX", "FTOXX", "FCOXX", "FISXX",
    # Schwab
    "SWVXX", "SNSXX", "SNVXX", "SWRXX", "MMDA1", "MMDA2",
    # Generic
    "CASH", "FCASH",
}
_PERIODS = {"1mo": "perf_1m", "3mo": "perf_3m", "ytd": "perf_ytd", "1y": "perf_1y"}

# Options look like "NVDA  280121C00200000" — long strings with spaces/digits
_OPTION_RE = re.compile(r".{1,6}\s+\d{6}[CP]\d+")


def _is_option(symbol: str) -> bool:
    return bool(_OPTION_RE.match(symbol)) or len(symbol) > 10


def _yf_symbol(symbol: str) -> str:
    """Yahoo Finance uses hyphens instead of dots (e.g. MOG.A -> MOG-A)."""
    return symbol.replace(".", "-")


def _pct(series) -> float | None:
    if series is None or len(series) < 2:
        return None
    f, l = series.iloc[0], series.iloc[-1]
    return round((l / f - 1) * 100, 2) if f else None


_CASH_NAME_KEYWORDS = ("money market", "cash reserves", "government mm", "treasury mm",
                       "municipal mm", "prime mm", "cash mgmt", "sweep", "treasury fund")


def _is_cash_fund(info: dict) -> bool:
    name = (info.get("longName") or info.get("shortName") or "").lower()
    cat = (info.get("category") or "").lower()
    return any(k in name or k in cat for k in _CASH_NAME_KEYWORDS)


def _infer_sector(info: dict) -> str:
    qt = info.get("quoteType", "").upper()
    cat = info.get("category", "").upper()
    if _is_cash_fund(info):
        return "Cash & Equivalents"
    if "BOND" in qt or "FIXED" in cat or "BOND" in cat:
        return "Fixed Income"
    if "ETF" in qt or "MUTUALFUND" in qt:
        return "Diversified"
    return "Unknown"


def _enrich_one(h: Holding) -> Holding:
    if h.asset_type in ("CASH", "OPTION") or h.symbol in CASH_LIKE:
        h.sector = "Cash & Equivalents" if h.asset_type != "OPTION" else "Options"
        h.country = "N/A"
        return h

    if _is_option(h.symbol):
        h.sector, h.asset_type = "Options", "OPTION"
        return h

    yf_sym = _yf_symbol(h.symbol)
    try:
        ticker = yf.Ticker(yf_sym)
        info = ticker.fast_info if hasattr(ticker, "fast_info") else {}
        full_info = ticker.info or {}

        h.sector = full_info.get("sector") or _infer_sector(full_info)
        h.industry = full_info.get("industry")
        h.country = full_info.get("country", "United States")

        for period, attr in _PERIODS.items():
            try:
                hist = ticker.history(period=period)
                setattr(h, attr, _pct(hist["Close"]) if not hist.empty else None)
            except Exception:
                pass

    except Exception as e:
        log.debug("yfinance enrichment skipped for %s: %s", h.symbol, e)

    return h


def enrich_holdings(holdings: list[Holding], max_workers: int = 8) -> list[Holding]:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_enrich_one, h): h for h in holdings}
        return [f.result() for f in as_completed(futures)]
