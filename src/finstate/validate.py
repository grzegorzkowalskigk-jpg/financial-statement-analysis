"""Automated data-quality checks that flag likely data artifacts.

These are NOT business red flags — they warn when the underlying numbers look
suspicious (a share count that jumps without a split, an extreme multiple, or
negative equity), so a reviewer can verify against a second source before
trusting the output. This turns silent data bugs into visible warnings.
"""

from __future__ import annotations

import pandas as pd

#: (ratio key, label, absolute threshold) for the extreme-multiple check.
EXTREME_MULTIPLES = [("pe", "P/E", 500), ("pb", "P/B", 100),
                     ("ps", "P/S", 50), ("ev_ebitda", "EV/EBITDA", 200)]


def _col(df: pd.DataFrame | None, name: str) -> pd.Series | None:
    if df is None or name not in getattr(df, "columns", []):
        return None
    return df[name]


def data_quality_flags(
    financials: pd.DataFrame,
    market: pd.DataFrame | None = None,
    ratios: pd.DataFrame | None = None,
) -> list[str]:
    """Return human-readable data-quality warnings (empty if nothing looks off)."""
    flags: list[str] = []

    # 1. Split-adjusted share count should move smoothly (buybacks/issuance),
    #    not jump multiples — a big jump signals a split/restatement artifact.
    #    Checked only for recent, material years (older filings are noisier and
    #    less scrutinised) and above a tiny-value floor.
    shares = _col(financials, "shares_diluted")
    if shares is not None and len(shares.dropna()):
        prev = shares.shift()
        cutoff = int(shares.dropna().index.max()) - 12
        for year in shares.index[1:]:
            if int(year) < cutoff:
                continue
            a, b = prev.get(year), shares.get(year)
            if pd.notna(a) and pd.notna(b) and a > 1e8 and b > 1e8:  # floor: 0.1B shares
                ratio = b / a
                if ratio > 1.8 or ratio < 0.55:
                    flags.append(
                        f"Share count changed {ratio:.1f}× in {int(year)} "
                        f"({a / 1e9:.2f}B → {b / 1e9:.2f}B) — possible split/restatement artifact."
                    )

    # 2. Extreme valuation multiples in the latest year.
    if ratios is not None and len(ratios):
        latest = ratios.iloc[-1]
        for key, label, threshold in EXTREME_MULTIPLES:
            value = latest.get(key)
            if pd.notna(value) and abs(value) > threshold:
                flags.append(
                    f"{label} of {value:,.0f} exceeds {threshold} in the latest year — "
                    "verify against a second source."
                )

    # 3. Negative equity distorts every equity-based ratio.
    equity = _col(financials, "equity")
    if equity is not None and len(equity) and pd.notna(equity.iloc[-1]) and equity.iloc[-1] < 0:
        flags.append(
            "Negative shareholders' equity in the latest year — "
            "ROE / P/B / equity multiplier may be misleading."
        )

    return flags
