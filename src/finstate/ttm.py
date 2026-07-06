"""Trailing-twelve-months (TTM) financials from SEC quarterly data.

Flow items (income statement, cash flow) use the standard TTM identity:

    TTM = last full fiscal year + current fiscal YTD − prior-year same YTD

This avoids the "missing Q4" problem (10-Q filings only cover Q1–Q3, so a clean
Q4 three-month figure is usually not filed). Balance-sheet items are point-in-time,
so TTM uses the most recent quarter's value.
"""

from __future__ import annotations

import pandas as pd

from . import config
from .edgar import _records, annual_series, build_financials, get_cik, get_company_facts
from .market import split_adjust_financials

#: Flow line items (aggregated over a period) → TTM identity.
FLOW_KEYS = {
    "revenue", "cost_of_revenue", "gross_profit", "operating_income", "pretax_income",
    "income_tax", "net_income", "interest_expense", "eps_diluted", "dividends_per_share",
    "operating_cash_flow", "capex", "depreciation_amortization",
}
#: Balance-sheet line items (point-in-time) → latest quarter's value.
INSTANT_KEYS = {
    "total_assets", "current_assets", "total_liabilities", "current_liabilities",
    "equity", "retained_earnings", "cash", "inventory", "receivables", "long_term_debt",
}


def _duration_rows(facts: dict, concept: str) -> pd.DataFrame:
    """All duration (start–end) records for a concept, deduped by latest filing."""
    records = _records(facts, concept)
    if not records:
        return pd.DataFrame()
    rows = []
    for r in records:
        start = r.get("start")
        if start is None:
            continue
        end = pd.to_datetime(r["end"])
        rows.append((pd.to_datetime(start), end, (end - pd.to_datetime(start)).days,
                     pd.to_datetime(r["filed"]), r["val"]))
    df = pd.DataFrame(rows, columns=["start", "end", "days", "filed", "val"])
    return df.sort_values("filed").drop_duplicates(["start", "end"], keep="last")


def ttm_flow(facts: dict, concept: str, last_fy_value: float) -> float:
    """TTM value for a flow concept via ``last_fy + current_ytd − prior_ytd``."""
    df = _duration_rows(facts, concept)
    if df.empty:
        return float("nan")

    latest_end = df["end"].max()
    ytd = df[df["end"] == latest_end].sort_values("days").iloc[-1]  # longest run ending latest
    if ytd["days"] >= 350:                       # latest period already a full year
        return float(ytd["val"])
    if pd.isna(last_fy_value):
        return float("nan")

    target_end = latest_end - pd.DateOffset(years=1)
    prior = df[(abs((df["end"] - target_end).dt.days) <= 20) & (abs(df["days"] - ytd["days"]) <= 20)]
    if prior.empty:
        return float("nan")
    prior_val = prior.sort_values("days").iloc[-1]["val"]
    return float(last_fy_value) + float(ytd["val"]) - float(prior_val)


def latest_instant(facts: dict, concept: str) -> float:
    """Most recent quarter's value for a balance-sheet (instant) concept."""
    records = _records(facts, concept)
    if not records:
        return float("nan")
    rows = [(pd.to_datetime(r["end"]), pd.to_datetime(r["filed"]), r["val"])
            for r in records if r.get("start") is None]
    if not rows:
        return float("nan")
    df = pd.DataFrame(rows, columns=["end", "filed", "val"])
    df = df.sort_values("filed").drop_duplicates("end", keep="last")
    return float(df.sort_values("end").iloc[-1]["val"])


def latest_quarter_end(facts: dict, reference: str = "Assets") -> pd.Timestamp | None:
    """Most recent reported period end (from an instant reference concept)."""
    records = _records(facts, reference)
    if not records:
        return None
    ends = [pd.to_datetime(r["end"]) for r in records if r.get("start") is None]
    return max(ends) if ends else None


def build_ttm_financials(ticker: str) -> pd.Series:
    """Build a TTM financials Series (same keys as the annual table)."""
    facts = get_company_facts(get_cik(ticker))
    data: dict[str, float] = {}

    for key, candidates in config.CONCEPTS.items():
        if key not in FLOW_KEYS and key not in INSTANT_KEYS:
            continue
        for concept in candidates:
            if key in FLOW_KEYS:
                annual = annual_series(facts, concept)
                value = ttm_flow(facts, concept, annual.iloc[-1]) if not annual.empty else float("nan")
            else:
                value = latest_instant(facts, concept)
            if pd.notna(value):
                data[key] = value
                break

    # Shares: reuse the latest split-adjusted annual count (roughly stable quarter to quarter).
    financials = split_adjust_financials(build_financials(ticker), ticker)
    if "shares_diluted" in financials.columns:
        data["shares_diluted"] = float(financials["shares_diluted"].iloc[-1])

    series = pd.Series(data, dtype=float)
    series.attrs["as_of"] = latest_quarter_end(facts)
    return series
