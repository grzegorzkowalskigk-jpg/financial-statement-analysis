"""SaaS / growth unit-economics metrics.

IMPORTANT: unlike the ratios in :mod:`finstate.ratios`, these metrics CANNOT be
derived from SEC filings. They need internal cohort / customer data (ARR, churn,
per-customer economics, headcount) that public financial statements do not
contain — companies sometimes disclose them in investor presentations. These
functions therefore take the required inputs as explicit arguments, so you can
plug in numbers from a deck or internal data.
"""

from __future__ import annotations


def net_dollar_retention(starting_arr: float, expansion: float, contraction: float, churn: float) -> float:
    """Net Dollar Retention (a.k.a. NRR), as a ratio.

    NDR = (starting ARR + expansion - contraction - churn) / starting ARR

    Interpretation:
        > 1.00 (100%): existing customers grow spend net of churn — the product
            "expands" on its own; best-in-class SaaS is > 1.20 (120%).
        = 1.00: expansion exactly offsets churn.
        < 1.00: the existing base is shrinking, so new-logo sales must run just
            to stand still — a warning sign for the durability of growth.
    """
    if not starting_arr:
        return float("nan")
    return (starting_arr + expansion - contraction - churn) / starting_arr


def cac_payback_months(sales_marketing: float, net_new_arr: float, gross_margin: float) -> float:
    """CAC payback period, in MONTHS.

    months = sales_marketing / (net_new_arr * gross_margin) * 12

    Interpretation:
        The number of months to recover the cost of acquiring customers from
        their gross-margin contribution.
        < 12 months: excellent — highly efficient acquisition.
        12-24 months: healthy for most SaaS.
        > 24 months: concerning — capital is tied up for a long time and the
            payback is sensitive to churn and rising acquisition costs.
    """
    denom = net_new_arr * gross_margin
    if not denom:
        return float("nan")
    return sales_marketing / denom * 12


def ltv_cac_ratio(arpa: float, gross_margin: float, churn_rate: float, cac: float) -> float:
    """LTV : CAC ratio.

    LTV = (arpa * gross_margin) / churn_rate      (customer lifetime value)
    ratio = LTV / CAC

    Interpretation:
        >= 3: healthy — each $1 spent on acquisition returns >= $3 of lifetime
            value (the common SaaS rule of thumb).
        1-3: viable but thin; watch acquisition efficiency and churn.
        < 1: unsustainable — you pay more to acquire a customer than they are
            worth.
        > 5: very strong, but can also signal under-investment in growth (you
            could afford to spend more to acquire customers faster).
    """
    if not churn_rate or not cac:
        return float("nan")
    ltv = (arpa * gross_margin) / churn_rate
    return ltv / cac


def arr_per_fte(arr: float, employees: float) -> float:
    """Annual Recurring Revenue per full-time employee.

    Interpretation:
        A productivity / capital-efficiency gauge. Rough SaaS benchmarks:
        ~$150k-250k per FTE is healthy, > $300k is best-in-class, and well below
        $150k suggests the org is over-staffed relative to recurring revenue.
        (For non-SaaS companies, plain revenue-per-employee is the analogue.)
    """
    if not employees:
        return float("nan")
    return arr / employees
