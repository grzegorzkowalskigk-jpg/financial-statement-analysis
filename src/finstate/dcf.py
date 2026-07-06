"""Discounted Cash Flow (DCF) intrinsic valuation.

A transparent two-stage FCF model: project free cash flow at a growth rate for
a number of years, discount it plus a Gordon-growth terminal value, subtract net
debt to get equity value, and divide by shares for intrinsic value per share.
All assumptions are explicit parameters so a dashboard can expose them as sliders.
"""

from __future__ import annotations

import pandas as pd

from .edgar import build_financials
from .market import build_market_data


def intrinsic_value(
    fcf0: float,
    shares: float,
    net_debt: float,
    growth: float = 0.08,
    years: int = 10,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.09,
) -> dict:
    """Two-stage DCF. Returns intrinsic value per share and the components.

    Args:
        fcf0: latest free cash flow (starting point).
        shares: diluted shares outstanding.
        net_debt: total debt minus cash (subtracted from enterprise value).
        growth: annual FCF growth during the projection stage.
        years: length of the projection stage.
        terminal_growth: perpetual growth after the projection stage.
        discount_rate: required return / WACC (must exceed terminal_growth).
    """
    if discount_rate <= terminal_growth:
        raise ValueError("discount_rate must be greater than terminal_growth")
    if fcf0 is None or shares in (None, 0) or pd.isna(fcf0) or pd.isna(shares):
        return {"intrinsic_value_per_share": float("nan")}

    pv_fcf = 0.0
    fcf = float(fcf0)
    for t in range(1, years + 1):
        fcf *= 1 + growth
        pv_fcf += fcf / (1 + discount_rate) ** t

    terminal_value = fcf * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** years

    enterprise_value = pv_fcf + pv_terminal
    equity_value = enterprise_value - (net_debt or 0.0)
    per_share = equity_value / shares

    return {
        "intrinsic_value_per_share": per_share,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "pv_of_fcf": pv_fcf,
        "pv_of_terminal": pv_terminal,
        "assumptions": {
            "fcf0": float(fcf0),
            "growth": growth,
            "years": years,
            "terminal_growth": terminal_growth,
            "discount_rate": discount_rate,
        },
    }


def implied_growth(
    price: float,
    fcf0: float,
    shares: float,
    net_debt: float,
    years: int = 5,
    terminal_growth: float = 0.025,
    discount_rate: float = 0.09,
    bounds: tuple[float, float] = (-0.90, 2.0),
    tol: float = 1e-4,
    max_iter: int = 100,
) -> float:
    """Reverse DCF: solve for the stage-1 FCF growth the current price implies.

    Intrinsic value increases monotonically with growth, so the implied growth is
    found by bisection. Returns the growth rate ``g`` such that the DCF value per
    share equals ``price`` (clamped to ``bounds`` if the price is outside range).
    """
    if price in (None, 0) or pd.isna(price) or pd.isna(fcf0) or shares in (None, 0) or pd.isna(shares):
        return float("nan")

    def value(g: float) -> float:
        return intrinsic_value(
            fcf0, shares, net_debt, growth=g, years=years,
            terminal_growth=terminal_growth, discount_rate=discount_rate,
        )["intrinsic_value_per_share"]

    lo, hi = bounds
    if value(lo) - price > 0:   # even the lowest growth over-values → below range
        return lo
    if value(hi) - price < 0:   # even the highest growth under-values → above range
        return hi

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        diff = value(mid) - price
        if abs(diff) < tol * price:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _latest_inputs(ticker: str):
    """Return (fcf0, shares, net_debt, fiscal-year-end price) for the latest year."""
    fin = build_financials(ticker)
    mkt = build_market_data(ticker)
    latest = fin.iloc[-1]
    fcf0 = float(latest.get("operating_cash_flow", float("nan"))) - float(latest.get("capex", float("nan")))
    shares = float(latest.get("shares_diluted", float("nan")))
    net_debt = float(latest.get("long_term_debt", 0.0) or 0.0) - float(latest.get("cash", 0.0) or 0.0)
    price = float(mkt.iloc[-1]["price"]) if not mkt.empty else float("nan")
    return fcf0, shares, net_debt, price


def reverse_dcf_from_ticker(ticker: str, price: float | None = None, **assumptions) -> dict:
    """Reverse DCF for a ticker: the FCF growth implied by ``price`` (or latest price)."""
    fcf0, shares, net_debt, fy_price = _latest_inputs(ticker)
    price = fy_price if price is None else price
    g = implied_growth(price, fcf0, shares, net_debt, **assumptions)
    return {"implied_growth": g, "price": price, "fcf0": fcf0}


def dcf_from_ticker(ticker: str, **assumptions) -> dict:
    """Run a DCF for a ticker using its latest FCF, shares and net debt.

    Extra keyword args (growth, years, terminal_growth, discount_rate) override
    the defaults. Adds current price and upside vs intrinsic value when available.
    """
    fin = build_financials(ticker)
    mkt = build_market_data(ticker)

    latest = fin.iloc[-1]
    fcf0 = float(latest.get("operating_cash_flow", float("nan"))) - float(latest.get("capex", float("nan")))
    shares = float(latest.get("shares_diluted", float("nan")))
    net_debt = float(latest.get("long_term_debt", 0.0) or 0.0) - float(latest.get("cash", 0.0) or 0.0)

    result = intrinsic_value(fcf0, shares, net_debt, **assumptions)

    price = float(mkt.iloc[-1]["price"]) if not mkt.empty else float("nan")
    iv = result.get("intrinsic_value_per_share", float("nan"))
    result["current_price"] = price
    result["upside"] = (iv / price - 1) if price and not pd.isna(price) and not pd.isna(iv) else float("nan")
    return result
