"""Configuration: SEC request headers and the map of XBRL concepts we extract.

The SEC requires a descriptive User-Agent with contact info on every request.
Override it via the ``SEC_USER_AGENT`` environment variable if needed.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

#: SEC requires a User-Agent identifying the caller (name + contact email).
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "finstate portfolio project contact@example.com"
)
SEC_HEADERS = {"User-Agent": SEC_USER_AGENT}

#: SEC endpoints.
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

#: Line items we pull, mapped to candidate US-GAAP concepts (first available wins).
#: Fallbacks handle companies that report under different concept names.
CONCEPTS: dict[str, list[str]] = {
    # Income statement (flow)
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss"],
    "dividends_per_share": ["CommonStockDividendsPerShareDeclared"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    # Balance sheet (instant)
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    # Cash flow (flow)
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
