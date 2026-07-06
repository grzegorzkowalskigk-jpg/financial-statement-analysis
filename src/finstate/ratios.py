"""Ratio engine: compute financial ratios and health scores from the raw data.

Inputs are the tidy annual tables from :mod:`finstate.edgar` (fundamentals) and
:mod:`finstate.market` (prices / market cap), both indexed by fiscal year.
Missing inputs propagate to ``NaN`` rather than raising, so a company that does
not report a given line item simply yields ``NaN`` for the affected ratios.
"""

from __future__ import annotations

import pandas as pd

from .edgar import build_financials
from .market import build_market_data, split_adjust_financials

DAYS_IN_YEAR = 365


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Return column ``name`` as a float Series, or an all-NaN series if absent."""
    if name in df.columns:
        return df[name].astype(float)
    return pd.Series(index=df.index, dtype=float)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Divide element-wise, returning NaN where the denominator is 0 or NaN."""
    den = den.where((den != 0) & den.notna())
    return num / den


def compute_ratios(
    financials: pd.DataFrame,
    market: pd.DataFrame | None = None,
    cost_of_capital: float = 0.09,
) -> pd.DataFrame:
    """Compute the continuous ratios (liquidity, profitability, leverage, ...).

    ``cost_of_capital`` is the required return used for the residual-income
    metrics (EVA / REVA); it defaults to 9% as a documented assumption.
    """
    f = financials
    r = pd.DataFrame(index=f.index)

    revenue = _col(f, "revenue")
    total_assets = _col(f, "total_assets")
    equity = _col(f, "equity")
    net_income = _col(f, "net_income")
    operating_income = _col(f, "operating_income")
    current_assets = _col(f, "current_assets")
    current_liabilities = _col(f, "current_liabilities")
    total_liabilities = _col(f, "total_liabilities")
    cash = _col(f, "cash")
    long_term_debt = _col(f, "long_term_debt")
    gross_profit = _col(f, "gross_profit")
    da = _col(f, "depreciation_amortization")
    ebitda = operating_income + da

    # --- Liquidity ---
    r["current_ratio"] = _safe_div(current_assets, current_liabilities)
    r["quick_ratio"] = _safe_div(current_assets - _col(f, "inventory"), current_liabilities)
    r["cash_ratio"] = _safe_div(cash, current_liabilities)

    # --- Profitability / margins ---
    r["gross_margin"] = _safe_div(gross_profit, revenue)
    r["operating_margin"] = _safe_div(operating_income, revenue)
    r["ebitda_margin"] = _safe_div(ebitda, revenue)
    r["pretax_margin"] = _safe_div(_col(f, "pretax_income"), revenue)
    r["net_margin"] = _safe_div(net_income, revenue)

    # --- Returns ---
    r["roa"] = _safe_div(net_income, total_assets)
    r["roe"] = _safe_div(net_income, equity)
    r["roce"] = _safe_div(operating_income, total_assets - current_liabilities)
    effective_tax = _safe_div(_col(f, "income_tax"), _col(f, "pretax_income"))
    nopat = operating_income * (1 - effective_tax)
    invested_capital = equity + long_term_debt - cash
    r["roic"] = _safe_div(nopat, invested_capital)
    r["ros"] = r["net_margin"]                    # Return on Sales (= net margin)
    r["s_bv"] = _safe_div(revenue, equity)        # Sales / Book Value
    # EVA (Economic Value Added): NOPAT above the charge for capital employed.
    r["eva"] = nopat - cost_of_capital * invested_capital

    # --- DuPont: ROE = net_margin × asset_turnover × equity_multiplier ---
    r["dupont_net_margin"] = r["net_margin"]
    r["dupont_asset_turnover"] = _safe_div(revenue, total_assets)
    r["dupont_equity_multiplier"] = _safe_div(total_assets, equity)

    # --- Leverage ---
    r["debt_to_equity"] = _safe_div(total_liabilities, equity)
    r["debt_to_assets"] = _safe_div(total_liabilities, total_assets)
    r["net_debt"] = long_term_debt - cash
    r["interest_coverage"] = _safe_div(operating_income, _col(f, "interest_expense"))

    # --- Efficiency ---
    r["asset_turnover"] = r["dupont_asset_turnover"]
    r["inventory_days"] = _safe_div(_col(f, "inventory") * DAYS_IN_YEAR, _col(f, "cost_of_revenue"))
    r["receivables_days"] = _safe_div(_col(f, "receivables") * DAYS_IN_YEAR, revenue)

    # --- Cash flow ---
    fcf = _col(f, "operating_cash_flow") - _col(f, "capex")
    r["fcf"] = fcf
    r["fcf_margin"] = _safe_div(fcf, revenue)

    # --- Growth (YoY) ---
    r["revenue_growth"] = revenue.pct_change()
    r["eps_growth"] = _col(f, "eps_diluted").pct_change()

    # --- Rule of 40 (golden rule of growth), in percentage points ---
    # For growth companies, revenue growth % + FCF margin % should exceed 40:
    # a company can justify low profitability with fast growth, or vice versa.
    r["rule_of_40"] = (r["revenue_growth"] + _safe_div(_col(f, "operating_cash_flow") - _col(f, "capex"), revenue)) * 100

    # --- Dividends ---
    dps = _col(f, "dividends_per_share")
    r["dps"] = dps
    r["dividend_payout"] = _safe_div(dps, _col(f, "eps_diluted"))
    r["retention_ratio"] = 1 - r["dividend_payout"]                  # e (reinvested earnings)
    r["sustainable_growth"] = r["roe"] * r["retention_ratio"]        # g = ROE × retention

    # --- Valuation (requires market data) ---
    if market is not None and not market.empty:
        market_cap = _col(market, "market_cap")
        price = _col(market, "price")
        ev = market_cap + long_term_debt - cash
        r["ev"] = ev
        r["pe"] = _safe_div(market_cap, net_income)
        r["pb"] = _safe_div(market_cap, equity)
        r["ev_sales"] = _safe_div(ev, revenue)
        r["ev_ebit"] = _safe_div(ev, operating_income)
        r["ev_ebitda"] = _safe_div(ev, ebitda)
        r["ev_gross_profit"] = _safe_div(ev, gross_profit)
        r["ev_fcf"] = _safe_div(ev, fcf)
        r["ps"] = _safe_div(market_cap, revenue)
        r["p_fcf"] = _safe_div(market_cap, fcf)
        r["p_ce"] = _safe_div(market_cap, net_income + da)     # Price / Cash Earnings (NI + D&A)
        r["fcf_yield"] = _safe_div(fcf, market_cap)
        r["dividend_yield"] = _safe_div(dps, price)
        # Value creation
        r["mva"] = market_cap - equity                        # Market Value Added
        r["reva"] = nopat - cost_of_capital * ev              # Refined EVA (market-based capital)
        # Tobin's q — replacement cost approximated by total (book) assets.
        r["tobin_q"] = _safe_div(market_cap + total_liabilities, total_assets)

    return r


def growth_cagr(series: pd.Series, years: int) -> float:
    """Compound annual growth rate over the last ``years`` full years."""
    s = series.dropna()
    if len(s) <= years:
        return float("nan")
    start, end = s.iloc[-1 - years], s.iloc[-1]
    if start <= 0 or end <= 0:
        return float("nan")
    return (end / start) ** (1 / years) - 1


def cagr_table(financials: pd.DataFrame, horizons: tuple[int, ...] = (3, 5, 10)) -> dict[str, float]:
    """Revenue and diluted-EPS CAGRs over several horizons (matches portal panels)."""
    out: dict[str, float] = {}
    for years in horizons:
        out[f"revenue_cagr_{years}y"] = growth_cagr(_col(financials, "revenue"), years)
        out[f"eps_cagr_{years}y"] = growth_cagr(_col(financials, "eps_diluted"), years)
    return out


def altman_z(financials: pd.DataFrame, market: pd.DataFrame | None = None) -> pd.Series:
    """Altman Z-score (bankruptcy risk). >2.99 safe, 1.81–2.99 grey, <1.81 distress."""
    f = financials
    total_assets = _col(f, "total_assets")
    working_capital = _col(f, "current_assets") - _col(f, "current_liabilities")
    market_cap = _col(market, "market_cap") if market is not None else _col(f, "__none__")

    a = _safe_div(working_capital, total_assets)
    b = _safe_div(_col(f, "retained_earnings"), total_assets)
    c = _safe_div(_col(f, "operating_income"), total_assets)  # EBIT proxy
    d = _safe_div(market_cap, _col(f, "total_liabilities"))
    e = _safe_div(_col(f, "revenue"), total_assets)
    return 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e


def piotroski_f(financials: pd.DataFrame) -> pd.Series:
    """Piotroski F-score (0–9): fundamental quality across 9 yearly criteria."""
    f = financials
    net_income = _col(f, "net_income")
    total_assets = _col(f, "total_assets")
    ocf = _col(f, "operating_cash_flow")
    roa = _safe_div(net_income, total_assets)
    current_ratio = _safe_div(_col(f, "current_assets"), _col(f, "current_liabilities"))
    ltd_ratio = _safe_div(_col(f, "long_term_debt"), total_assets)
    gross_margin = _safe_div(_col(f, "gross_profit"), _col(f, "revenue"))
    asset_turnover = _safe_div(_col(f, "revenue"), total_assets)
    shares = _col(f, "shares_diluted")

    signals = pd.DataFrame(index=f.index)
    signals["profit_positive"] = (net_income > 0).astype(int)      # 1. ROA > 0
    signals["cfo_positive"] = (ocf > 0).astype(int)                # 2. CFO > 0
    signals["roa_up"] = (roa > roa.shift()).astype(int)            # 3. ROA improving
    signals["accruals"] = (ocf > net_income).astype(int)           # 4. CFO > net income
    signals["leverage_down"] = (ltd_ratio < ltd_ratio.shift()).astype(int)   # 5. LT debt ratio down
    signals["liquidity_up"] = (current_ratio > current_ratio.shift()).astype(int)  # 6. current ratio up
    signals["no_dilution"] = (shares <= shares.shift()).astype(int)          # 7. no new shares
    signals["margin_up"] = (gross_margin > gross_margin.shift()).astype(int)  # 8. gross margin up
    signals["turnover_up"] = (asset_turnover > asset_turnover.shift()).astype(int)  # 9. turnover up

    fscore = signals.sum(axis=1).astype(float)
    # The first year has no prior year for 5 of the 9 criteria — mark it incomplete.
    if len(fscore):
        fscore.iloc[0] = float("nan")
    return fscore


def analyze(ticker: str) -> pd.DataFrame:
    """Fetch data for a ticker and return all ratios plus health scores by year.

    Per-share metrics are split-adjusted so multi-year comparisons are valid.
    """
    financials = split_adjust_financials(build_financials(ticker), ticker)
    market = build_market_data(ticker)
    ratios = compute_ratios(financials, market)
    ratios["altman_z"] = altman_z(financials, market)
    ratios["piotroski_f"] = piotroski_f(financials)
    return ratios
