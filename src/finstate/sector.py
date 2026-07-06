"""Sector comparison: benchmark a company against a universe of sector peers.

SEC filings have no sector-aggregate endpoint, so "the sector" here is a
representative sample of large listed companies (editable by the user), not
literally every company in the sector.
"""

from __future__ import annotations

import pandas as pd

from .ratios import analyze

#: Representative large-cap universes per sector (editable in the dashboard).
SECTOR_UNIVERSES: dict[str, list[str]] = {
    "Big Tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "Semiconductors": ["NVDA", "AMD", "INTC", "AVGO", "QCOM", "TXN"],
    "Software": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU"],
    "Retail": ["WMT", "COST", "TGT", "HD", "LOW"],
    "Big Banks": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "Pharma": ["JNJ", "PFE", "MRK", "ABBV", "LLY", "BMY"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
    "Consumer Staples": ["PG", "KO", "PEP", "CL", "MDLZ"],
}

#: Metrics shown in the sector table (a broad cross-section of the ratio engine).
SECTOR_METRICS: list[str] = [
    "gross_margin", "operating_margin", "ebitda_margin", "net_margin",
    "roa", "roe", "roce", "roic",
    "pe", "pb", "ps", "ev_ebitda", "ev_ebit", "p_fcf",
    "fcf_margin", "fcf_yield", "dividend_yield",
    "current_ratio", "quick_ratio", "debt_to_equity", "interest_coverage",
    "rule_of_40", "altman_z", "piotroski_f",
]


def sector_ratios(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return (latest-year metrics per ticker, {ticker: error}) for a universe.

    Each row is the latest fiscal year's values for :data:`SECTOR_METRICS`.
    Tickers that fail to load are collected in the errors dict, not raised.
    """
    rows: dict[str, dict[str, float]] = {}
    errors: dict[str, str] = {}

    for raw in tickers:
        ticker = raw.strip().upper()
        if not ticker:
            continue
        try:
            latest = analyze(ticker).iloc[-1]
            rows[ticker] = {m: float(latest.get(m, float("nan"))) for m in SECTOR_METRICS}
        except Exception as exc:  # noqa: BLE001 - report per-ticker, keep going
            errors[ticker] = str(exc)

    df = pd.DataFrame(rows).T
    if not df.empty:
        df = df[SECTOR_METRICS]
    return df, errors
