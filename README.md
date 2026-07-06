# Financial Statement Analysis

An interactive **Streamlit dashboard** that pulls company fundamentals straight
from **SEC EDGAR**, computes a broad set of financial ratios and valuation
models, and benchmarks a company against peers and its sector. Built as a
portfolio project for markets / analyst work — free data, no paid API key.

## Highlights
- **Data straight from filings** — SEC EDGAR XBRL, with careful handling of
  restatements, changing XBRL tags and stock-split adjustments (see data notes).
- **Ratio engine** — liquidity, profitability, DuPont ROE, leverage, efficiency,
  ~20 valuation multiples, value creation (EVA / REVA / MVA / Tobin's q), growth
  CAGRs, Altman Z and Piotroski F.
- **Valuation** — trailing & **TTM** multiples on a live daily price, an
  interactive two-stage **DCF**, and a **reverse DCF** (the growth the price implies).
- **Context** — searchable company picker, peer comparison, and a sector benchmark
  (company vs sector median / min / max / percentile).
- **Data-quality guardrails** — automated checks that flag likely data artifacts
  (e.g. a share count that jumps without a split).

## Roadmap
- [x] **Phase 1** — SEC EDGAR data layer (ticker → CIK, annual & TTM financials, restatement/split handling)
- [x] **Phase 2** — ratio engine + two-stage & reverse DCF + forward metrics + data-quality checks
- [x] **Phase 3** — Streamlit dashboard (searchable picker, trends, DCF, unit economics, peers, sector)
- [x] **Phase 4** — write-up and published

## Run the dashboard

```bash
pip install -e .
# set SEC_USER_AGENT="Your Name your@email.com" in a .env file, then:
streamlit run app.py
```

Enter a US-listed ticker (e.g. `AAPL`, `MSFT`) in the sidebar. The dashboard
shows headline KPIs, red-flag screens, and tabs for profitability & returns
(with DuPont, CAGRs, Rule of 40), valuation (multiples + value creation +
forward estimates), health & scores (Altman Z, Piotroski F), an interactive
forward & reverse DCF, SaaS unit economics (manual inputs), a peer comparison
across several tickers, and a sector benchmark table (company vs sector
median / min / max / percentile for all metrics).

## What this project demonstrates
- **Working with messy real-world data** — SEC XBRL is inconsistent (restatements,
  retroactive split adjustments, changing concept tags). The code documents and
  handles each quirk rather than hiding it.
- **Financial modelling** — DuPont decomposition, DCF (forward & reverse), EVA/REVA,
  Altman Z, Piotroski F, TTM roll-ups.
- **Point-in-time thinking** — split-consistent market caps read from the original
  filings, plus automated anomaly detection to catch data errors.
- **Communicating analysis** — an interactive dashboard, not just a script.

## Example insights
- **Apple** trades at a very high **P/B (~50×)** with **ROE > 150%** — not from
  supernormal returns on assets, but because years of buybacks have shrunk book
  equity. DuPont makes it explicit: the *equity multiplier* (leverage), not margin
  or asset turnover, drives that ROE.
- **NVIDIA**'s FY2023 **P/E ~117** is a genuine earnings trough (post-crypto), not
  a glitch — an earlier build showed ~1,200 until a split-restatement bug was
  fixed and a data-quality check was added to catch that class of error.
- **Rule of 40**: mature large-caps like Apple sit ~30 (below the 40 growth bar)
  while Microsoft clears it — the metric cleanly separates growth from maturity.

## Data source
[SEC EDGAR XBRL company-facts API](https://www.sec.gov/edgar/sec-api-documentation) —
free, official, no key required (a descriptive User-Agent is required).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (source .venv/bin/activate on Linux/macOS)
pip install -e .
```

```python
from finstate import build_financials

df = build_financials("AAPL")   # annual financials indexed by fiscal year
print(df.tail())
```

> Set a `SEC_USER_AGENT` (e.g. `"Your Name your@email.com"`) in a `.env` file so
> your requests identify you as the SEC requests.

## Data notes & limitations

Real filings are messy. Quirks found while building this are recorded here as
they come up — being explicit about data quality is part of the analysis.

- **Interest expense often missing.** Apple and Microsoft do not report a
  standalone `InterestExpense` in recent filings (interest is netted within
  other financial income/expense lines). Interest-coverage ratios will fall
  back gracefully or show `n/a` rather than a wrong number.
- **Restatements are de-duplicated.** A period can appear in several filings
  (originals + restatements). We keep the value from the **most recently filed**
  10-K for each fiscal-year period.
- **Annual (10-K) history + TTM.** Trend charts and multi-year ratios use annual
  filings; the dashboard also derives trailing-twelve-months (TTM) figures from
  10-Q data for the current-valuation view (see the TTM note below).
- **Fiscal-year labeling.** Rows are keyed by the calendar year of the period
  end date. Companies with non-December year-ends (e.g. Apple ends in September,
  some retailers in January) are labeled by that end year — a minor caveat when
  comparing across companies with different fiscal calendars.
- **Market prices come from a second source.** EDGAR has no share prices, so
  valuation ratios use Yahoo Finance (`yfinance`) prices combined with EDGAR
  share counts. Market cap per fiscal year = closing price on/before the
  fiscal year-end × weighted-average diluted shares (an approximation of
  point-in-time shares outstanding). Prices are split-adjusted but not
  dividend-adjusted, so market cap stays correct.
- **Stock splits are reconciled.** Yahoo prices are split-adjusted to current
  terms; share counts are taken from the original filing and multiplied by the
  cumulative post-period split factor (from Yahoo split data), so historical
  market caps stay consistent across splits (e.g. Apple 2020, NVIDIA 2021/2024).
  See the per-share note below for why the *original* filing matters.
- **Per-share metrics are split-adjusted (from the original filing).** EPS,
  dividends-per-share and share counts are restated into current (post-split)
  terms using Yahoo split data, so multi-year CAGRs and historical market caps
  that span a split are valid. Crucially, these are read from the **original**
  10-K filing (earliest, not latest): EDGAR *retroactively* restates share
  counts for later splits in some years (e.g. NVIDIA's 2021 4:1 and 2024 10:1),
  and using the restated value would double-count the split factor — which
  otherwise produced absurd market caps / P/E (e.g. NVDA showing ~250B shares
  and a P/E near 1,200 for FY2023).
- **Concept fallbacks are merged, not just first-match.** Line items are pulled
  from multiple candidate US-GAAP concepts (e.g. revenue from
  `RevenueFromContractWithCustomerExcludingAssessedTax` → `Revenues` →
  `SalesRevenueNet`). The candidates are **merged** so that a company that
  changed its XBRL tag over time still gets full history (the newer tag wins
  where both exist; older tags backfill earlier years).
- **Net debt excludes marketable securities.** `net_debt` = long-term debt −
  cash & equivalents. It does **not** subtract short/long-term marketable
  securities, so cash-rich companies (e.g. Apple) can show positive net debt
  despite a true net-cash position. Treat net debt here as conservative.
- **TTM uses the last-FY + YTD − prior-YTD identity.** Trailing-twelve-months
  figures avoid the "missing Q4" problem (10-Q filings only cover Q1–Q3, so a
  clean Q4 three-month value is usually not filed) by computing
  `TTM = last full fiscal year + current fiscal YTD − prior-year same YTD` for
  flow items; balance-sheet items use the most recent quarter. The live-price
  multiples at the top of the dashboard use TTM fundamentals.
- **Sector comparison is a sample, not the whole sector.** SEC filings have no
  sector-aggregate endpoint, so the Sector tab benchmarks against an editable
  large-cap sample per sector, and its percentile is positional within that
  sample — not the full population of listed companies.
- **ROIC is capital-structure sensitive.** Invested capital = equity + long-term
  debt − cash; for companies with large buybacks / net cash this can be small
  and inflate ROIC. Read it alongside ROCE.

## Metric assumptions & scope

- **EVA / REVA** use a **default 9% cost of capital** (a documented assumption,
  not an estimated WACC per company). Pass `cost_of_capital=` to
  `compute_ratios()` to change it.
- **Tobin's q** approximates asset replacement cost with **total book assets**
  (true replacement cost is not in filings), so read it as an indicator.
- **Sustainable growth** g = ROE × retention ratio; **retention (e)** = 1 − payout.
- **Not included (by design):** *CVA* and *SVA* need forward cash-flow forecasts
  and capital-charge adjustments beyond reported statements (and *SVA* overlaps
  the DCF module); the empirical "growth P/E" is a niche correlation method. The
  SaaS unit-economics metrics (NDR, CAC payback, LTV:CAC, ARR/FTE) are **not**
  in filings — see [`unit_economics.py`](src/finstate/unit_economics.py); the
  dashboard takes them as manual inputs.

## License
[Apache License 2.0](LICENSE)
