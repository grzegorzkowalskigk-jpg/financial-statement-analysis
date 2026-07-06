"""Streamlit dashboard for financial statement analysis.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

import altair as alt
import pandas as pd
import streamlit as st

from finstate import build_financials, build_market_data, cagr_table, compute_ratios, get_forward_metrics
from finstate.compare import peer_comparison
from finstate.edgar import company_directory
from finstate.sector import SECTOR_METRICS, SECTOR_UNIVERSES, sector_ratios
from finstate.ttm import build_ttm_financials
from finstate.dcf import implied_growth, intrinsic_value
from finstate.market import get_close_prices, split_adjust_financials
from finstate.ratios import altman_z, piotroski_f
from finstate.unit_economics import arr_per_fte, cac_payback_months, ltv_cac_ratio, net_dollar_retention
from finstate.validate import data_quality_flags

st.set_page_config(page_title="Financial Statement Analysis", page_icon="📊", layout="wide")

# Persist the user's peer / sector picks across sessions (local single-user file).
STATE_FILE = pathlib.Path(__file__).parent / ".dashboard_state.json"


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001 - missing/corrupt file → start fresh
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=1))
    except Exception:  # noqa: BLE001 - best-effort persistence
        pass


STATE = load_state()


# --- formatting helpers ------------------------------------------------------

def fmt_usd(x: float) -> str:
    if x is None or pd.isna(x):
        return "n/a"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= div:
            return f"${x / div:,.2f}{unit}"
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:,.1f}%"


def fmt_x(x: float) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x:,.1f}"


def _div(a, b) -> float:
    """Safe division returning NaN on a zero/NaN denominator."""
    if b in (None, 0) or pd.isna(a) or pd.isna(b):
        return float("nan")
    return a / b


def price_chart(prices: pd.Series) -> None:
    """Daily close-price chart (date x-axis) with a wide hover hit-area."""
    df = prices.rename("Price").reset_index()
    df.columns = ["Date", "Price"]
    x = alt.X("Date:T", axis=alt.Axis(title=None, format="%Y",
                                      tickCount={"interval": "year", "step": 1}))
    y = alt.Y("Price:Q", scale=alt.Scale(zero=False),
              axis=alt.Axis(title="Price ($)", titleAngle=0, titleAnchor="end"))
    base = alt.Chart(df)
    line = base.mark_line(color="#4c78a8").encode(x=x, y=y)
    hover = base.mark_line(strokeWidth=18, opacity=0).encode(
        x=x, y=y,
        tooltip=[alt.Tooltip("Date:T", title="Date"),
                 alt.Tooltip("Price:Q", format="$,.2f", title="Close")],
    )
    st.altair_chart(alt.layer(line, hover).properties(height=220).interactive(),
                    use_container_width=True)


# Pretty labels: uppercase acronyms and multi-word names without underscores.
METRIC_LABELS = {
    "roa": "ROA", "roe": "ROE", "roce": "ROCE", "roic": "ROIC", "ros": "ROS",
    "ebitda_margin": "EBITDA Margin",
    "pe": "P/E", "pb": "P/B", "ps": "P/S", "p_fcf": "P/FCF", "p_ce": "P/CE",
    "ev_ebitda": "EV/EBITDA", "ev_ebit": "EV/EBIT", "ev_sales": "EV/Sales",
    "ev_fcf": "EV/FCF", "ev_gross_profit": "EV/Gross Profit",
    "fcf": "FCF", "fcf_margin": "FCF Margin", "fcf_yield": "FCF Yield",
    "s_bv": "S/BV", "dps": "DPS", "eva": "EVA", "reva": "REVA", "mva": "MVA",
    "tobin_q": "Tobin's q", "debt_to_equity": "D/E", "debt_to_assets": "D/A",
    "ev": "EV", "market_cap": "Market Cap", "rule_of_40": "Rule of 40",
}

#: Categorical palette shared between chart lines and the metric dots.
PALETTE = ["#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2", "#eeca3b", "#b279a2", "#ff9da6"]


def nice(col: str) -> str:
    """Human-readable metric label (uppercase acronyms, no underscores)."""
    return METRIC_LABELS.get(col, col.replace("_", " ").title())


def color_map(cols: list[str]) -> dict[str, str]:
    """Map each (nice) metric name to a stable palette color."""
    return {nice(c): PALETTE[i % len(PALETTE)] for i, c in enumerate(cols)}


def dot_label(label: str, color: str) -> str:
    """Metric name followed by a large colored dot (matches its chart line)."""
    return (f"**{label}** <span style='color:{color};font-size:36px;line-height:0;"
            f"vertical-align:middle'>●</span>")


def line_chart(ratios: pd.DataFrame, cols: list[str], scale: float = 1.0,
               unit: str = "%", y_title: str = "%",
               colors: dict[str, str] | None = None, legend: bool = True,
               chart_label: str = "📈 Show trend chart") -> None:
    """Render an interactive Altair line chart.

    Horizontal year ticks (no thousands separator), horizontal y-axis title,
    a tooltip showing 2 decimals + the unit, pan/zoom, and a wide hover hit-area
    (a transparent thick line over the thin visible one). Pass ``colors`` to fix
    the series colors and ``legend=False`` to hide the legend.
    """
    present = [c for c in cols if c in ratios.columns]
    df = (ratios[present].dropna(how="all") * scale).rename(columns={c: nice(c) for c in present})
    df.index.name = "Year"
    long = df.reset_index().melt("Year", var_name="Series", value_name="value").dropna(subset=["value"])
    long["Year"] = long["Year"].astype(int)
    long = long.sort_values(["Series", "Year"])
    long["change"] = long.groupby("Series")["value"].diff()   # year-over-year change

    legend_cfg = alt.Legend(orient="bottom", title=None) if legend else None
    if colors:
        color_enc = alt.Color("Series:N", legend=legend_cfg,
                              scale=alt.Scale(domain=list(colors), range=list(colors.values())))
    else:
        color_enc = alt.Color("Series:N", legend=legend_cfg)

    x = alt.X("Year:Q", axis=alt.Axis(format="d", title="Year", labelAngle=0))
    y = alt.Y("value:Q", axis=alt.Axis(title=y_title, titleAngle=0, titleAnchor="end"))
    suffix = f" {unit}" if unit else ""
    base = alt.Chart(long).transform_calculate(
        display="format(datum.value, '.2f') + '" + suffix + "'",
        change_display="datum.change == null ? 'n/a' : (datum.change >= 0 ? '+' : '') "
                       "+ format(datum.change, '.2f') + '" + suffix + "'",
    )

    line = base.mark_line(point=True).encode(x=x, y=y, color=color_enc)
    # Transparent thick line widens the hover hit-area without changing the visible width.
    hover = base.mark_line(strokeWidth=18, opacity=0).encode(
        x=x, y=y, color=color_enc,
        tooltip=[
            alt.Tooltip("Year:Q", format="d", title="Year"),
            alt.Tooltip("Series:N", title="Series"),
            alt.Tooltip("display:N", title="Value"),
            alt.Tooltip("change_display:N", title="Change"),
        ],
    )
    chart = alt.layer(line, hover).properties(height=340).interactive()
    with st.expander(chart_label, expanded=False):
        st.altair_chart(chart, use_container_width=True)


def metric_yoy(container, label: str, key: str, latest, ratios: pd.DataFrame,
               kind: str = "x", delta_color: str = "normal", color: str | None = None) -> None:
    """Render a metric with its year-over-year change as a colored direction arrow.

    kind: "x" (ratio/multiple), "pct" (percentage), "usd" (money, no delta).
    delta_color: "normal" (up=green), "inverse" (down=green), "off" (grey).
    color: if given, show a matching colored dot before the name (in place of a chart legend).
    """
    val = latest.get(key, float("nan"))
    prev = ratios[key].iloc[-2] if (key in ratios.columns and len(ratios) >= 2) else float("nan")
    delta = None
    if kind == "pct":
        disp = fmt_pct(val)
        if pd.notna(val) and pd.notna(prev):
            delta = f"{(val - prev) * 100:+.1f} pp"
    elif kind == "usd":
        disp = fmt_usd(val)
    else:
        disp = fmt_x(val)
        if pd.notna(val) and pd.notna(prev):
            delta = f"{val - prev:+.2f}"
    if color:
        container.markdown(dot_label(label, color), unsafe_allow_html=True)
        container.metric(label, disp, delta, delta_color=delta_color, label_visibility="collapsed")
    else:
        container.metric(label, disp, delta, delta_color=delta_color)


# --- data loading (cached) ---------------------------------------------------

@st.cache_data(show_spinner="Fetching filings from SEC EDGAR…")
def load(ticker: str):
    financials = split_adjust_financials(build_financials(ticker), ticker)
    market = build_market_data(ticker)
    ratios = compute_ratios(financials, market)
    ratios["altman_z"] = altman_z(financials, market)
    ratios["piotroski_f"] = piotroski_f(financials)
    return financials, market, ratios, cagr_table(financials), get_forward_metrics(ticker)


@st.cache_data(show_spinner="Comparing peers…")
def load_peers(tickers: tuple[str, ...]):
    return peer_comparison(list(tickers))


@st.cache_data(show_spinner="Loading sector sample…")
def load_sector(tickers: tuple[str, ...]):
    return sector_ratios(list(tickers))


@st.cache_data(ttl=86400, show_spinner=False)
def load_price_history(ticker: str, years: int = 5) -> pd.Series:
    """Daily close prices for the last ``years`` years, refreshed once a day."""
    start = pd.Timestamp.today() - pd.DateOffset(years=years)
    return get_close_prices(ticker, start)


@st.cache_data(show_spinner="Computing TTM…")
def load_ttm(ticker: str):
    """TTM financials Series and its as-of date (attrs don't survive caching)."""
    ttm = build_ttm_financials(ticker)
    return ttm, ttm.attrs.get("as_of")


# --- sidebar -----------------------------------------------------------------

@st.cache_data(ttl=86400, show_spinner=False)
def load_directory() -> dict[str, str]:
    """{ticker: company name} for all SEC-listed companies."""
    return company_directory()


# Searchable "Company Name (TICKER)" options shared by all company pickers.
_directory = load_directory()
OPTIONS = {f"{name} ({tk})": tk for tk, name in sorted(_directory.items(), key=lambda kv: kv[1].lower())}
DISPLAY_BY_TICKER = {tk: disp for disp, tk in OPTIONS.items()}
DISPLAY_LIST = list(OPTIONS)


def displays_for(tickers: list[str]) -> list[str]:
    """Map tickers to their display strings, skipping any not in the directory."""
    return [DISPLAY_BY_TICKER[t] for t in tickers if t in DISPLAY_BY_TICKER]


st.sidebar.title("📊 Financial Analysis")
_default = DISPLAY_BY_TICKER.get("AAPL", DISPLAY_LIST[0])
_selected = st.sidebar.selectbox("Company (type a name or ticker)", DISPLAY_LIST,
                                 index=DISPLAY_LIST.index(_default))
ticker = OPTIONS[_selected]

PERIODS = {"5 years": 5, "10 years": 10, "15 years": 15, "20 years": 20, "Max": None}
n_years = PERIODS[st.sidebar.selectbox("History", list(PERIODS), index=1)]
st.sidebar.caption("Data: SEC EDGAR (fundamentals) + Yahoo Finance (prices, estimates).")

try:
    financials, market, ratios, cagr, forward = load(ticker)
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not load data for {ticker!r}: {exc}")
    st.stop()

# Limit the trend history to the selected window (charts use `ratios`).
if n_years:
    ratios = ratios[ratios.index >= int(ratios.index.max()) - n_years + 1]

latest = ratios.iloc[-1]
year = int(ratios.index[-1])
fin_latest = financials.iloc[-1]

st.title(f"{ticker} — Financial Statement Analysis")
st.caption(f"Latest fiscal year: {year}")

# --- live price + TTM current-price multiples (top of the page) --------------
# Match the price chart's span to the fundamentals charts (same year range).
price_years = max(1, pd.Timestamp.today().year - int(ratios.index.min()))
prices = load_price_history(ticker, price_years)
ttm, ttm_as_of = load_ttm(ticker)
ttm_r = compute_ratios(pd.DataFrame([ttm])).iloc[0] if not ttm.empty else None

if not prices.empty:
    current_price = float(prices.iloc[-1])
    live_cap = current_price * float(fin_latest.get("shares_diluted", float("nan")))
    src = ttm if not ttm.empty else fin_latest   # TTM fundamentals, else latest annual
    pr = st.columns(5)
    pr[0].metric("Price (last close)", f"${current_price:,.2f}")
    pr[1].metric("P/E (TTM)", fmt_x(_div(live_cap, src.get("net_income"))))
    pr[2].metric("P/B (TTM)", fmt_x(_div(live_cap, src.get("equity"))))
    pr[3].metric("P/S (TTM)", fmt_x(_div(live_cap, src.get("revenue"))))
    pr[4].metric("Market cap (now)", fmt_usd(live_cap))

if not ttm.empty and ttm_r is not None:
    st.markdown(f"**TTM (trailing twelve months)** — through "
                f"{ttm_as_of.date() if ttm_as_of is not None else 'n/a'}")
    ttm_fcf = ttm.get("operating_cash_flow", float("nan")) - ttm.get("capex", float("nan"))
    tt = st.columns(5)
    tt[0].metric("Revenue (TTM)", fmt_usd(ttm.get("revenue")))
    tt[1].metric("Net income (TTM)", fmt_usd(ttm.get("net_income")))
    tt[2].metric("FCF (TTM)", fmt_usd(ttm_fcf))
    tt[3].metric("Net margin (TTM)", fmt_pct(ttm_r.get("net_margin")))
    tt[4].metric("Gross margin (TTM)", fmt_pct(ttm_r.get("gross_margin")))

if not prices.empty:
    price_chart(prices)
    st.caption("Last completed session's close (refreshed daily). Multiples use the live price "
               "with **TTM** (trailing-twelve-months) fundamentals.")

# Fiscal-year-end market cap (used by the Valuation "Size" section below).
market_cap = market.iloc[-1]["market_cap"] if not market.empty else float("nan")

# --- red flags ---------------------------------------------------------------

flags = []
if latest.get("altman_z", float("nan")) < 1.81:
    flags.append("Altman Z below 1.81 — elevated bankruptcy risk.")
if latest.get("current_ratio", float("nan")) < 1:
    flags.append("Current ratio below 1 — short-term liquidity is tight.")
if latest.get("net_margin", float("nan")) < 0:
    flags.append("Negative net margin — the company is unprofitable.")
if latest.get("revenue_growth", float("nan")) < 0:
    flags.append("Revenue declined year over year.")
if latest.get("fcf", float("nan")) < 0:
    flags.append("Negative free cash flow — burning cash.")
if latest.get("piotroski_f", float("nan")) <= 2:
    flags.append("Low Piotroski F-score (≤2) — weak fundamental trend.")

if flags:
    with st.expander(f"⚠️ {len(flags)} red flag(s)", expanded=False):
        for f in flags:
            st.warning(f)
else:
    st.success("No red flags triggered by the basic screens.")

# --- data-quality checks (data artifacts, not business signals) ---------------

dq_flags = data_quality_flags(financials, market, ratios)
with st.expander(f"⚙️ Data quality — {len(dq_flags)} note(s)" if dq_flags
                 else "⚙️ Data quality — no anomalies", expanded=False):
    if dq_flags:
        for f in dq_flags:
            st.warning(f)
    else:
        st.success("No data-quality anomalies detected by the automated checks.")

# --- tabs --------------------------------------------------------------------

tab_prof, tab_val, tab_health, tab_dcf, tab_unit, tab_peers, tab_sector = st.tabs(
    ["Profitability & Returns", "Valuation", "Health & Scores", "DCF", "Unit Economics", "Peers", "Sector"]
)

with tab_prof:
    st.caption("Colored dots match the trend lines below; arrows show the year-over-year change.")

    st.subheader("Margins")
    margin_cols = ["gross_margin", "operating_margin", "ebitda_margin", "net_margin"]
    mc = color_map(margin_cols)
    for col_ui, key in zip(st.columns(len(margin_cols)), margin_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "pct", "normal", color=mc[nice(key)])
    line_chart(ratios, margin_cols, scale=100, unit="%", y_title="%", colors=mc, legend=False)

    st.subheader("Returns")
    return_cols = ["roa", "roe", "roce", "roic"]
    rtc = color_map(return_cols)
    for col_ui, key in zip(st.columns(len(return_cols)), return_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "pct", "normal", color=rtc[nice(key)])
    line_chart(ratios, return_cols, scale=100, unit="%", y_title="%", colors=rtc, legend=False)

    st.subheader("DuPont Decomposition of ROE")
    st.caption("ROE = Net Margin (profitability) × Asset Turnover (efficiency) "
               "× Equity Multiplier (leverage)")
    dp = st.columns(4)
    dp[0].metric("Net Margin", fmt_pct(latest.get("dupont_net_margin")))
    dp[1].metric("× Asset Turnover", fmt_x(latest.get("dupont_asset_turnover")))
    dp[2].metric("× Equity Multiplier", fmt_x(latest.get("dupont_equity_multiplier")))
    dp[3].metric("= ROE", fmt_pct(latest.get("roe")))

    st.subheader("Growth (CAGR)")
    g1 = st.columns(4)
    g1[0].markdown("**Revenue CAGR**")
    g1[1].metric("3Y", fmt_pct(cagr.get("revenue_cagr_3y")))
    g1[2].metric("5Y", fmt_pct(cagr.get("revenue_cagr_5y")))
    g1[3].metric("10Y", fmt_pct(cagr.get("revenue_cagr_10y")))
    g2 = st.columns(4)
    g2[0].markdown("**Diluted EPS CAGR**")
    g2[1].metric("3Y", fmt_pct(cagr.get("eps_cagr_3y")))
    g2[2].metric("5Y", fmt_pct(cagr.get("eps_cagr_5y")))
    g2[3].metric("10Y", fmt_pct(cagr.get("eps_cagr_10y")))

    st.subheader("Rule of 40 & sustainable growth")
    ro40 = latest.get("rule_of_40")
    gm = st.columns(4)
    gm[0].metric("Rule of 40", "n/a" if pd.isna(ro40) else f"{ro40:.1f}",
                 None if pd.isna(ro40) else ("✅ ≥ 40" if ro40 >= 40 else "⚠️ below 40"))
    gm[1].metric("Sustainable growth (g)", fmt_pct(latest.get("sustainable_growth")))
    gm[2].metric("Retention (e)", fmt_pct(latest.get("retention_ratio")))
    st.caption("Rule of 40 = revenue growth % + FCF margin % (should exceed 40). "
               "Sustainable growth g = ROE × retention; retention e = 1 − payout.")

with tab_val:
    st.caption("Colored dots match the trend lines below. Direction arrows show the "
               "year-over-year change: for multiples a fall (cheaper) is green, for yields a rise is green.")

    st.subheader("Price-based multiples")
    price_cols = ["pe", "pb", "ps", "p_ce", "p_fcf"]
    pc = color_map(price_cols)
    for col_ui, key in zip(st.columns(5), price_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "x", "inverse", color=pc[nice(key)])
    line_chart(ratios, price_cols, unit="×", y_title="", colors=pc, legend=False)

    st.subheader("Enterprise-value multiples")
    ev_cols = ["ev_sales", "ev_ebit", "ev_ebitda", "ev_fcf", "ev_gross_profit"]
    ec = color_map(ev_cols)
    for col_ui, key in zip(st.columns(5), ev_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "x", "inverse", color=ec[nice(key)])
    line_chart(ratios, ev_cols, unit="×", y_title="", colors=ec, legend=False)

    st.subheader("Yields")
    yield_cols = ["dividend_yield", "fcf_yield"]
    yc = color_map(yield_cols)
    for col_ui, key in zip(st.columns(2), yield_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "pct", "normal", color=yc[nice(key)])
    line_chart(ratios, yield_cols, scale=100, unit="%", y_title="%", colors=yc, legend=False)

    st.subheader("Size (enterprise value & market cap)")
    size_df = ratios[["ev"]].copy()
    size_df["market_cap"] = market["market_cap"]
    sc = color_map(["ev", "market_cap"])
    s = st.columns(2)
    for col_ui, key, value in ((s[0], "ev", latest.get("ev")), (s[1], "market_cap", market_cap)):
        col_ui.markdown(dot_label(nice(key), sc[nice(key)]), unsafe_allow_html=True)
        col_ui.metric(nice(key), fmt_usd(value), label_visibility="collapsed")
    line_chart(size_df, ["ev", "market_cap"], scale=1e-9, unit="$B", y_title="$B", colors=sc, legend=False)

    st.subheader("Value creation")
    coc = st.slider("Cost of capital (for EVA / REVA)", 5.0, 15.0, 9.0, 0.5, format="%.1f%%") / 100
    # Recompute EVA/REVA at the chosen cost of capital (latest fiscal year).
    eff_tax = _div(fin_latest.get("income_tax"), fin_latest.get("pretax_income"))
    nopat = fin_latest.get("operating_income", float("nan")) * (1 - eff_tax)
    invested_capital = (fin_latest.get("equity", 0.0) + fin_latest.get("long_term_debt", 0.0)
                        - fin_latest.get("cash", 0.0))
    vc = st.columns(4)
    vc[0].metric("EVA", fmt_usd(nopat - coc * invested_capital))
    vc[1].metric("REVA", fmt_usd(nopat - coc * latest.get("ev", float("nan"))))
    vc[2].metric("MVA", fmt_usd(latest.get("mva")))
    vc[3].metric("Tobin's q", fmt_x(latest.get("tobin_q")))
    st.caption("EVA/REVA use the cost of capital set above. Positive EVA = returns above the cost "
               "of capital. Tobin's q > 1 = market values the firm above its (book-approximated) "
               "asset replacement cost.")

    st.subheader("Forward (analyst estimates)")
    f = st.columns(4)
    f[0].metric("Forward P/E", fmt_x(forward.get("forward_pe")))
    f[1].metric("Trailing P/E", fmt_x(forward.get("trailing_pe")))
    f[2].metric("PEG", fmt_x(forward.get("peg_ratio")))
    tgt = forward.get("price_target_mean")
    cur = forward.get("current_price")
    f[3].metric("Price target", "n/a" if tgt is None else f"${tgt:,.2f}",
                None if (tgt is None or cur is None or cur == 0) else f"{(tgt/cur - 1) * 100:+.1f}%")

with tab_health:
    st.caption("Colored dots match the trend lines; arrows show the year-over-year change. "
               "For liquidity higher is safer; for leverage lower is safer.")

    st.subheader("Liquidity")
    liq_cols = ["current_ratio", "quick_ratio", "cash_ratio"]
    liqc = color_map(liq_cols)
    for col_ui, key in zip(st.columns(3), liq_cols):
        metric_yoy(col_ui, nice(key), key, latest, ratios, "x", "normal", color=liqc[nice(key)])
    line_chart(ratios, liq_cols, unit="×", y_title="", colors=liqc, legend=False)

    st.subheader("Leverage")
    lev_cols = ["debt_to_equity", "debt_to_assets"]
    levc = color_map(lev_cols)
    lv = st.columns(3)
    metric_yoy(lv[0], nice("debt_to_equity"), "debt_to_equity", latest, ratios, "x", "inverse", color=levc["D/E"])
    metric_yoy(lv[1], nice("debt_to_assets"), "debt_to_assets", latest, ratios, "x", "inverse", color=levc["D/A"])
    metric_yoy(lv[2], nice("interest_coverage"), "interest_coverage", latest, ratios, "x", "normal")
    line_chart(ratios, lev_cols, unit="×", y_title="", colors=levc, legend=False)
    st.caption("Interest coverage has no dot — it is not on the chart above (it is often "
               "very large or n/a, which would distort the ratio scale).")

    st.subheader("Net debt")
    ndc = color_map(["net_debt"])
    nd = st.columns(3)
    metric_yoy(nd[0], "Net debt", "net_debt", latest, ratios, "usd", color=ndc["Net Debt"])
    line_chart(ratios, ["net_debt"], scale=1e-9, unit="$B", y_title="$B", colors=ndc, legend=False)
    st.caption("Net debt = long-term debt − cash & equivalents (excludes marketable securities), "
               "so cash-rich firms can still show positive net debt. Negative = net cash position.")

    st.subheader("Health scores")
    c = st.columns(2)
    z = latest.get("altman_z", float("nan"))
    z_zone = "🟢 Safe" if z > 2.99 else "🟡 Grey" if z > 1.81 else "🔴 Distress"
    c[0].metric("Altman Z-score", fmt_x(z), z_zone if pd.notna(z) else None, delta_color="off")
    pf = latest.get("piotroski_f", float("nan"))
    c[1].metric("Piotroski F-score", "n/a" if pd.isna(pf) else f"{int(pf)} / 9")
    line_chart(ratios, ["altman_z"], unit="", y_title="Z-score", legend=False)

with tab_dcf:
    st.subheader("Two-stage DCF")
    c = st.columns(4)
    growth = c[0].slider("FCF growth", 0.0, 20.0, 8.0, 0.5, format="%.1f%%") / 100
    discount = c[1].slider("Discount rate", 5.0, 15.0, 9.0, 0.5, format="%.1f%%") / 100
    terminal = c[2].slider("Terminal growth", 0.0, 4.0, 2.5, 0.25, format="%.1f%%") / 100
    years = c[3].slider("Projection years", 5, 15, 10)

    fcf0 = float(fin_latest.get("operating_cash_flow", float("nan"))) - float(fin_latest.get("capex", float("nan")))
    shares = float(fin_latest.get("shares_diluted", float("nan")))
    net_debt = float(fin_latest.get("long_term_debt", 0.0) or 0.0) - float(fin_latest.get("cash", 0.0) or 0.0)

    try:
        res = intrinsic_value(fcf0, shares, net_debt, growth=growth, years=years,
                              terminal_growth=terminal, discount_rate=discount)
        iv = res["intrinsic_value_per_share"]
        price = float(market.iloc[-1]["price"]) if not market.empty else float("nan")
        upside = (iv / price - 1) if price and not pd.isna(price) and not pd.isna(iv) else float("nan")

        r = st.columns(3)
        r[0].metric("Intrinsic value / share", "n/a" if pd.isna(iv) else f"${iv:,.2f}")
        r[1].metric("Price (fiscal year-end)", "n/a" if pd.isna(price) else f"${price:,.2f}")
        r[2].metric("Upside / (downside)", fmt_pct(upside),
                    None if pd.isna(upside) else ("undervalued" if upside > 0 else "overvalued"))
        st.caption(f"Starting FCF: {fmt_usd(fcf0)} · net debt: {fmt_usd(net_debt)} · "
                   f"terminal value {fmt_usd(res.get('pv_of_terminal'))} of "
                   f"{fmt_usd(res.get('enterprise_value'))} EV.")

        st.divider()
        st.subheader("Reverse DCF — growth implied by the price")
        rev_years = st.slider("Projection years (reverse)", 3, 15, 5)
        implied = implied_growth(price, fcf0, shares, net_debt, years=rev_years,
                                 terminal_growth=terminal, discount_rate=discount)
        hist = cagr.get("revenue_cagr_5y")
        rc = st.columns(2)
        rc[0].metric("Implied FCF growth", fmt_pct(implied))
        rc[1].metric("Historical revenue CAGR (5Y)", fmt_pct(hist))
        st.caption(
            f"At {'n/a' if pd.isna(price) else f'${price:,.2f}'}, a {rev_years}-year DCF "
            f"(discount {discount:.1%}, terminal {terminal:.1%}) implies ~{fmt_pct(implied)} "
            f"annual FCF growth. Compare it with the historical trend to judge whether the "
            f"market's expectation looks achievable."
        )
    except ValueError as exc:
        st.error(str(exc))

with tab_unit:
    st.subheader("SaaS / growth unit economics")
    st.info("These metrics are **not** in SEC filings — they need internal cohort / customer "
            "data (ARR, churn, per-customer economics, headcount). Enter values, e.g. from an "
            "investor deck, to compute them. Interpretation notes are in `unit_economics.py`.")

    with st.expander("Net Dollar Retention (NDR)", expanded=True):
        c = st.columns(4)
        s_arr = c[0].number_input("Starting ARR ($)", min_value=0.0, value=100_000_000.0, step=1e6, format="%.0f")
        exp = c[1].number_input("Expansion ($)", min_value=0.0, value=25_000_000.0, step=1e6, format="%.0f")
        con = c[2].number_input("Contraction ($)", min_value=0.0, value=5_000_000.0, step=1e6, format="%.0f")
        chn = c[3].number_input("Churn ($)", min_value=0.0, value=8_000_000.0, step=1e6, format="%.0f")
        st.metric("Net Dollar Retention", fmt_pct(net_dollar_retention(s_arr, exp, con, chn)))
        st.caption("> 100% = base expands on its own (best-in-class > 120%); < 100% = shrinking base.")

    with st.expander("CAC payback period"):
        c = st.columns(3)
        sm = c[0].number_input("Sales & marketing spend ($)", min_value=0.0, value=40_000_000.0, step=1e6, format="%.0f")
        nna = c[1].number_input("Net new ARR ($)", min_value=0.0, value=30_000_000.0, step=1e6, format="%.0f")
        gm = c[2].number_input("Gross margin", min_value=0.0, max_value=1.0, value=0.75, step=0.01)
        payback = cac_payback_months(sm, nna, gm)
        st.metric("CAC payback (months)", "n/a" if pd.isna(payback) else f"{payback:.1f}")
        st.caption("< 12 months excellent · 12–24 healthy · > 24 concerning.")

    with st.expander("LTV : CAC"):
        c = st.columns(4)
        arpa = c[0].number_input("ARPA ($/yr)", min_value=0.0, value=12_000.0, step=500.0, format="%.0f")
        gm2 = c[1].number_input("Gross margin ", min_value=0.0, max_value=1.0, value=0.75, step=0.01)
        churn = c[2].number_input("Annual churn rate", min_value=0.0, max_value=1.0, value=0.10, step=0.01)
        cac = c[3].number_input("CAC ($)", min_value=0.0, value=15_000.0, step=500.0, format="%.0f")
        ratio = ltv_cac_ratio(arpa, gm2, churn, cac)
        st.metric("LTV : CAC", "n/a" if pd.isna(ratio) else f"{ratio:.1f}x")
        st.caption("≥ 3 healthy · 1–3 thin · < 1 unsustainable · > 5 may signal under-investment in growth.")

    with st.expander("ARR per FTE"):
        c = st.columns(2)
        default_arr = float(fin_latest.get("revenue", 0.0) or 0.0)
        arr = c[0].number_input("ARR ($, defaults to latest revenue)", min_value=0.0, value=default_arr, step=1e6, format="%.0f")
        emp = c[1].number_input("Full-time employees", min_value=0, value=1000, step=100)
        st.metric("ARR per FTE", fmt_usd(arr_per_fte(arr, emp)))
        st.caption("~$150k–250k healthy · > $300k best-in-class. ARR ≈ revenue proxy; not from filings.")

with tab_peers:
    st.subheader("Peer comparison")
    peer_display = st.multiselect(
        "Peer companies (search by name or ticker)", DISPLAY_LIST,
        default=displays_for(STATE.get("peers", ["MSFT", "GOOGL", "AMZN"])),
    )
    peer_tickers = [OPTIONS[d] for d in peer_display]
    STATE["peers"] = peer_tickers                       # remember for next session
    save_state(STATE)
    peer_list = list(dict.fromkeys([ticker] + peer_tickers))
    df_cmp, peer_errors = load_peers(tuple(peer_list))
    for tk, err in peer_errors.items():
        st.warning(f"{tk}: {err}")

    if df_cmp.empty:
        st.info("No peer data to show.")
    else:
        pct_cols = {"net_margin", "roe", "roic", "fcf_margin", "revenue_cagr_5y"}
        names = {"pe": "P/E", "pb": "P/B", "ps": "P/S", "ev_ebitda": "EV/EBITDA",
                 "net_margin": "Net margin", "roe": "ROE", "roic": "ROIC",
                 "fcf_margin": "FCF margin", "rule_of_40": "Rule of 40",
                 "debt_to_equity": "D/E", "altman_z": "Altman Z",
                 "piotroski_f": "Piotroski F", "revenue_cagr_5y": "Rev CAGR 5Y"}
        disp = df_cmp.copy()
        for col in disp.columns:
            as_pct = col in pct_cols
            disp[col] = disp[col].map(
                lambda v, p=as_pct: "n/a" if pd.isna(v) else (f"{v * 100:.1f}%" if p else f"{v:.1f}")
            )
        st.dataframe(disp.rename(columns=names), width="stretch")

        st.subheader("Visual comparison")
        cc = st.columns(3)
        cc[0].caption("ROE (%)")
        cc[0].bar_chart(df_cmp["roe"] * 100)
        cc[1].caption("P/E")
        cc[1].bar_chart(df_cmp["pe"])
        cc[2].caption("Altman Z")
        cc[2].bar_chart(df_cmp["altman_z"])

with tab_sector:
    st.subheader("Sector comparison")
    st.caption("Benchmarks the company against a representative large-cap sample of its sector — "
               "SEC filings have no sector aggregate, so this is an editable sample, not every "
               "listed company. Percentile is positional (100% = highest value in the sample).")
    sector_name = st.selectbox("Sector", list(SECTOR_UNIVERSES))
    _sector_state = STATE.get("sector", {})
    sector_display = st.multiselect(
        "Sector companies (search by name or ticker)", DISPLAY_LIST,
        default=displays_for(_sector_state.get(sector_name, SECTOR_UNIVERSES[sector_name])),
        key=f"sector_ms_{sector_name}",
    )
    sector_tickers = [OPTIONS[d] for d in sector_display]
    _sector_state[sector_name] = sector_tickers          # remember per sector
    STATE["sector"] = _sector_state
    save_state(STATE)
    universe = list(dict.fromkeys([ticker] + sector_tickers))
    df_sec, sec_errors = load_sector(tuple(universe))
    for tk, err in sec_errors.items():
        st.warning(f"{tk}: {err}")

    if df_sec.empty or ticker not in df_sec.index:
        st.info("Not enough sector data (make sure the analysed ticker is among the sector tickers).")
    else:
        pct_metrics = {"gross_margin", "operating_margin", "ebitda_margin", "net_margin",
                       "roa", "roe", "roce", "roic", "fcf_margin", "fcf_yield", "dividend_yield"}

        def cell(metric, value):
            if pd.isna(value):
                return "n/a"
            return f"{value * 100:.1f}%" if metric in pct_metrics else f"{value:.1f}"

        med, mn, mx = df_sec.median(), df_sec.min(), df_sec.max()
        company, rank_pct = df_sec.loc[ticker], df_sec.rank(pct=True)
        rows = []
        for m in SECTOR_METRICS:
            pr = rank_pct[m].get(ticker, float("nan"))
            rows.append({
                "Metric": nice(m),
                ticker: cell(m, company[m]),
                "Sector median": cell(m, med[m]),
                "Min": cell(m, mn[m]),
                "Max": cell(m, mx[m]),
                "Percentile": "n/a" if pd.isna(pr) else f"{pr * 100:.0f}%",
            })
        st.caption(f"Sector sample ({len(df_sec)}): {', '.join(df_sec.index)}")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

st.caption("Educational project — not investment advice. Data may contain gaps; see README data notes.")
