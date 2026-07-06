"""Forward-looking metrics from analyst estimates (Yahoo Finance).

These are NOT in SEC filings — they are consensus estimates, so they live in a
separate module and are clearly derived from a third party. Values may be missing
or occasionally stale; callers should treat ``None`` gracefully.
"""

from __future__ import annotations

import yfinance as yf


def get_forward_metrics(ticker: str) -> dict[str, float | None]:
    """Return forward-looking valuation metrics for a ticker (or None values).

    Includes forward P/E, forward EPS, trailing P/E, PEG, the mean analyst price
    target and dividend yield. Fails soft: on any error all values are None.
    """
    keys = {
        "forward_pe": "forwardPE",
        "forward_eps": "forwardEps",
        "trailing_pe": "trailingPE",
        "peg_ratio": "trailingPegRatio",
        "price_target_mean": "targetMeanPrice",
        "current_price": "currentPrice",
        "dividend_yield": "dividendYield",
    }
    try:
        info = yf.Ticker(ticker).info
    except Exception:  # noqa: BLE001 - third-party data, fail soft
        info = {}
    return {name: info.get(src) for name, src in keys.items()}
