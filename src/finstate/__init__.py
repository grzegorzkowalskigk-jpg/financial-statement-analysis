"""finstate — financial statement analysis from SEC EDGAR data.

Public API: the EDGAR data layer (and, in later phases, the ratio engine).
"""

from __future__ import annotations

from . import compare, config, dcf, edgar, estimates, market, ratios, sector, ttm, unit_economics, validate
from .compare import peer_comparison
from .sector import sector_ratios
from .ttm import build_ttm_financials
from .validate import data_quality_flags
from .dcf import dcf_from_ticker, implied_growth, intrinsic_value, reverse_dcf_from_ticker
from .edgar import build_financials, get_cik
from .estimates import get_forward_metrics
from .market import build_market_data
from .ratios import analyze, cagr_table, compute_ratios

__all__ = [
    "compare", "config", "dcf", "edgar", "estimates", "market", "ratios", "unit_economics",
    "build_financials", "get_cik", "build_market_data", "compute_ratios",
    "analyze", "cagr_table", "dcf_from_ticker", "intrinsic_value",
    "implied_growth", "reverse_dcf_from_ticker", "get_forward_metrics",
    "peer_comparison", "sector", "sector_ratios", "ttm", "build_ttm_financials",
    "validate", "data_quality_flags",
]
