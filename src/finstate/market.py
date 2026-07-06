"""Market-price layer: fetch prices and build market cap aligned to fiscal years.

SEC EDGAR has no market prices, so valuation ratios (P/E, P/B, EV/EBITDA) need
an external price source. Prices come from Yahoo Finance; share counts come from
EDGAR (weighted-average diluted shares). Market cap for each fiscal year uses the
closing price on/before that fiscal year-end date.
"""

from __future__ import annotations

import datetime as dt
import functools

import pandas as pd
import yfinance as yf

from .edgar import annual_series, fiscal_year_end_dates, get_cik, get_company_facts

#: EDGAR concept used as the share count for market cap.
SHARES_CONCEPT = "WeightedAverageNumberOfDilutedSharesOutstanding"

#: Per-share metrics scale inversely with splits; share counts scale directly.
PER_SHARE_DIVIDE = ("eps_diluted", "dividends_per_share")
SHARE_COUNT_MULTIPLY = ("shares_diluted",)


@functools.lru_cache(maxsize=32)
def get_splits(ticker: str) -> pd.Series:
    """Return a timezone-naive Series of split ratios (date -> ratio) from Yahoo."""
    try:
        splits = yf.Ticker(ticker).splits
    except Exception:  # noqa: BLE001 - third-party data, fail soft
        return pd.Series(dtype=float)
    if splits is None or splits.empty:
        return pd.Series(dtype=float)
    splits = splits.copy()
    splits.index = splits.index.tz_localize(None)
    return splits


def _future_split_factors(year_ends: dict[int, pd.Timestamp], splits: pd.Series) -> dict[int, float]:
    """For each fiscal year, the product of split ratios that occur AFTER its end.

    Multiplying an old value by this factor restates it in current (post-split)
    share terms; dividing restates a per-share figure the same way.
    """
    factors: dict[int, float] = {}
    for year, end_date in year_ends.items():
        if splits.empty:
            factors[year] = 1.0
        else:
            future = splits[splits.index > pd.Timestamp(end_date)]
            factors[year] = float(future.prod()) if len(future) else 1.0
    return factors


def split_adjust_financials(financials: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Restate per-share metrics and share counts into current (post-split) terms.

    EPS and dividends-per-share are divided by the cumulative future split factor;
    share counts are multiplied. Non-per-share items are left untouched.
    """
    facts = get_company_facts(get_cik(ticker))
    factors = _future_split_factors(fiscal_year_end_dates(facts), get_splits(ticker))
    factor = pd.Series(factors).reindex(financials.index).fillna(1.0)

    out = financials.copy()
    for col in PER_SHARE_DIVIDE:
        if col in out.columns:
            out[col] = out[col] / factor
    for col in SHARE_COUNT_MULTIPLY:
        if col in out.columns:
            out[col] = out[col] * factor
    return out


def get_close_prices(ticker: str, start: dt.datetime, end: dt.datetime | None = None) -> pd.Series:
    """Return a timezone-naive daily close-price series from Yahoo Finance.

    Uses ``auto_adjust=False`` and the raw ``Close`` (split-adjusted, but NOT
    dividend-adjusted) so that market cap = price × shares stays correct. A
    dividend-adjusted close would understate historical market caps.
    """
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if data.empty:
        return pd.Series(dtype=float)
    close = data["Close"]
    # A single ticker yields MultiIndex columns; flatten to a Series.
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = close.index.tz_localize(None)
    return close.sort_index()


def build_market_data(ticker: str) -> pd.DataFrame:
    """Build per-fiscal-year market data for a ticker.

    Returns a DataFrame indexed by fiscal year with columns ``price``, ``shares``
    and ``market_cap`` (price on/before the fiscal year-end × diluted shares).
    """
    facts = get_company_facts(get_cik(ticker))
    year_ends = fiscal_year_end_dates(facts)
    # Original-filing share count (keep="first") so applying the split factor
    # below is not double-counted against EDGAR's retroactive split restatements.
    shares = annual_series(facts, SHARES_CONCEPT, keep="first")
    if not year_ends:
        return pd.DataFrame()

    start = min(year_ends.values()) - pd.Timedelta(days=10)
    prices = get_close_prices(ticker, start)
    # Restate share counts into current terms so market cap is split-consistent
    # (Yahoo prices are already split-adjusted to current terms).
    factors = _future_split_factors(year_ends, get_splits(ticker))

    rows: dict[int, dict[str, float]] = {}
    for year, end_date in year_ends.items():
        price = prices.asof(pd.Timestamp(end_date)) if not prices.empty else float("nan")
        n_shares = float(shares.get(year, float("nan"))) * factors.get(year, 1.0)
        market_cap = price * n_shares if pd.notna(price) and pd.notna(n_shares) else float("nan")
        rows[year] = {"price": price, "shares": n_shares, "market_cap": market_cap}

    df = pd.DataFrame(rows).T.sort_index()
    df.index.name = "fiscal_year"
    return df
