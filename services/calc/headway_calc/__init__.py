"""headway_calc — Headway's deterministic calculation library (walking skeleton, ADR-0009).

The ONLY place any reported number originates. Pure, versioned, deterministic
functions: no network, no clock reads, no randomness, no hidden state.

All calculations in this package are v0 (pre-verification): they are
walking-skeleton approximations that MUST be verified against the current
published FTA NTD Reporting Manual before any figure is treated as reportable.
See REGULATORY_TRACKER.md.
"""

from headway_calc.types import BlockingIssue, CalcResult, VehiclePosition
from headway_calc.vrm import compute_vrm
from headway_calc.vrh import compute_vrh

__all__ = [
    "BlockingIssue",
    "CalcResult",
    "VehiclePosition",
    "compute_vrm",
    "compute_vrh",
]
