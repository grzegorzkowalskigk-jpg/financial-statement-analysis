"""Peer comparison across multiple tickers.

Builds a latest-year snapshot of key ratios for a set of companies so they can
be ranked side by side (valuation, profitability, growth, leverage, quality).
"""

from __future__ import annotations

import pandas as pd

from .edgar import build_financials
from .ratios import analyze, cagr_table

#: Metrics shown in the peer table (all available from the ratio engine).
PEER_METRICS = [
    "pe", "pb", "ps", "ev_ebitda",
    "net_margin", "roe", "roic", "fcf_margin",
    "rule_of_40", "debt_to_equity", "altman_z", "piotroski_f",
]


def peer_comparison(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return (comparison DataFrame indexed by ticker, {ticker: error}).

    Each row is the latest fiscal year's key metrics plus 5-year revenue CAGR.
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
            row = {m: float(latest.get(m, float("nan"))) for m in PEER_METRICS}
            row["revenue_cagr_5y"] = cagr_table(build_financials(ticker)).get("revenue_cagr_5y")
            rows[ticker] = row
        except Exception as exc:  # noqa: BLE001 - report per-ticker, keep going
            errors[ticker] = str(exc)

    df = pd.DataFrame(rows).T
    if not df.empty:
        df = df[PEER_METRICS + ["revenue_cagr_5y"]]
    return df, errors
