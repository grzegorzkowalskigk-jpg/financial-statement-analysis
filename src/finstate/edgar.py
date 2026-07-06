"""SEC EDGAR data layer: map tickers to CIK and extract annual financials.

Data comes from the SEC's free XBRL "company facts" API. Annual figures are
taken from 10-K filings and de-duplicated across restatements by keeping the
value from the most recently filed report for each fiscal-year period.
"""

from __future__ import annotations

import functools

import pandas as pd
import requests

from .config import COMPANY_FACTS_URL, CONCEPTS, SEC_HEADERS, TICKERS_URL


def _get_json(url: str) -> dict:
    """GET a JSON document from the SEC with the required headers."""
    resp = requests.get(url, headers=SEC_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


@functools.lru_cache(maxsize=1)
def _ticker_to_cik() -> dict[str, str]:
    """Return a cached mapping of upper-case ticker -> zero-padded 10-digit CIK."""
    data = _get_json(TICKERS_URL)
    return {row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()}


def get_cik(ticker: str) -> str:
    """Resolve a ticker to its 10-digit CIK, or raise if unknown."""
    cik = _ticker_to_cik().get(ticker.upper())
    if cik is None:
        raise ValueError(f"Unknown ticker: {ticker!r}")
    return cik


@functools.lru_cache(maxsize=1)
def company_directory() -> dict[str, str]:
    """Return a cached mapping of upper-case ticker -> company name (SEC-listed)."""
    data = _get_json(TICKERS_URL)
    return {row["ticker"].upper(): row["title"] for row in data.values()}


@functools.lru_cache(maxsize=32)
def get_company_facts(cik: str) -> dict:
    """Fetch the full XBRL company-facts document for a CIK (cached per process)."""
    return _get_json(COMPANY_FACTS_URL.format(cik=cik))


def fiscal_year_end_dates(facts: dict, reference: str = "Assets") -> dict[int, pd.Timestamp]:
    """Map fiscal year -> period-end date, from an instant reference concept.

    ``Assets`` is used by default because it is reported at every fiscal-year end.
    Values are de-duplicated by keeping the most recently filed 10-K per period.
    """
    records = _records(facts, reference)
    if not records:
        return {}
    rows = [
        (pd.to_datetime(r["end"]), pd.to_datetime(r["filed"]))
        for r in records
        if r.get("form") == "10-K" and r.get("start") is None
    ]
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["end", "filed"])
    df = df.sort_values("filed").drop_duplicates("end", keep="last")
    df["fiscal_year"] = df["end"].dt.year
    df = df.sort_values("end").drop_duplicates("fiscal_year", keep="last")
    return dict(zip(df["fiscal_year"], df["end"]))


def _records(facts: dict, concept: str) -> list[dict] | None:
    """Return the raw fact records for a us-gaap concept (USD preferred)."""
    node = facts.get("facts", {}).get("us-gaap", {}).get(concept)
    if not node:
        return None
    units = node.get("units", {})
    for unit in ("USD", "USD/shares"):
        if unit in units:
            return units[unit]
    return next(iter(units.values()), None)


def annual_series(facts: dict, concept: str, keep: str = "last") -> pd.Series:
    """Extract an annual (10-K) series for one concept, indexed by fiscal year.

    Handles both duration items (income/cash-flow, kept only for full fiscal
    years) and instant items (balance sheet).

    ``keep`` chooses which filing to keep per period: ``"last"`` (most recent —
    good for restated totals) or ``"first"`` (the original filing — needed for
    split-sensitive per-share items, since EDGAR retroactively restates those
    for later splits in some years, which would double-count our split factor).
    """
    records = _records(facts, concept)
    if not records:
        return pd.Series(dtype=float)

    rows = []
    for r in records:
        if r.get("form") != "10-K":
            continue
        end = pd.to_datetime(r["end"])
        start = r.get("start")
        if start is not None:  # duration item — keep full fiscal years only
            if not 350 <= (end - pd.to_datetime(start)).days <= 380:
                continue
        rows.append((end, pd.to_datetime(r["filed"]), r["val"]))

    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows, columns=["end", "filed", "val"])
    df = df.sort_values("filed").drop_duplicates("end", keep=keep)
    df["fiscal_year"] = df["end"].dt.year
    df = df.sort_values("end").drop_duplicates("fiscal_year", keep="last")
    return pd.Series(df["val"].to_numpy(), index=df["fiscal_year"].to_numpy(), name=concept)


def build_financials(ticker: str, concepts: dict[str, list[str]] = CONCEPTS) -> pd.DataFrame:
    """Build a tidy annual financials table for a ticker.

    Returns a DataFrame indexed by fiscal year, with one column per line item
    from ``concepts`` (using the first candidate concept that has data).
    """
    facts = get_company_facts(get_cik(ticker))
    data: dict[str, pd.Series] = {}
    # Split-sensitive per-share items use the ORIGINAL filing (keep="first") so
    # our split adjustment is not double-counted against EDGAR's own restatements.
    original_keys = {"shares_diluted", "eps_diluted", "dividends_per_share"}
    for name, candidates in concepts.items():
        keep = "first" if name in original_keys else "last"
        # Merge all candidate concepts (not just the first): the preferred concept
        # wins where present, earlier-named concepts backfill older years. This
        # matters when a company changed XBRL tags over time (e.g. revenue).
        merged: pd.Series | None = None
        for concept in candidates:
            series = annual_series(facts, concept, keep=keep)
            if series.empty:
                continue
            merged = series if merged is None else merged.combine_first(series)
        if merged is not None:
            data[name] = merged
    df = pd.DataFrame(data).sort_index()
    df.index.name = "fiscal_year"
    return df
