"""Great-circle distance (haversine) in statute miles. Stdlib only.

Computation policy
------------------
Per-leg distances are computed in binary float (IEEE-754 double) for speed and
simplicity; ONLY the final aggregate of a calculation is converted to Decimal,
via :func:`miles_to_decimal`. Intermediate legs are never individually rounded
— rounding once, at the end, avoids accumulating per-leg rounding error.

Rounding rule (documented, pre-verification)
--------------------------------------------
The final aggregate is quantized to 0.01 (two decimal places) using
ROUND_HALF_EVEN (banker's rounding), applied to ``Decimal(str(x))`` — i.e. the
shortest decimal string that round-trips the float. This is an explicit
engineering choice for v0, NOT a verified FTA convention: the rounding/unit
convention for reportable VRM must be verified against the current published
FTA NTD Reporting Manual and recorded in REGULATORY_TRACKER.md before any
figure is treated as reportable.

Earth model: sphere of mean radius 6371.0088 km = 3958.7613 statute miles
(IUGG mean Earth radius; synthetic v0 constant, adequate for a walking
skeleton; geodesic accuracy is out of scope for v0).
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal

#: Mean Earth radius in statute miles (6371.0088 km / 1.609344 km-per-mile).
EARTH_RADIUS_MILES: float = 3958.7613

#: Quantum for final Decimal aggregates: 0.01 mile.
MILES_QUANTUM = Decimal("0.01")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in statute miles between two (lat, lon) points.

    Pure function; float in, float out. Inputs in decimal degrees.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_MILES * c


def miles_to_decimal(total_miles: float) -> Decimal:
    """Convert a final float aggregate to Decimal, quantized to 0.01 mile.

    Rounding rule: Decimal(str(x)) then quantize(0.01, ROUND_HALF_EVEN).
    See module docstring — this rule is pre-verification.
    """
    return Decimal(str(total_miles)).quantize(MILES_QUANTUM, rounding=ROUND_HALF_EVEN)
