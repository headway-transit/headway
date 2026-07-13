"""sampling_v0 — NTD ready-to-use sampling plan support (handoff 0012).

Three deterministic, pure facilities for agencies WITHOUT full APC/TIDES
coverage — the counterpart to pmt_v0's 100%-count path:

1. **Plan selector** — (mode, unit, efficiency option, frequency) → the
   required per-period and annual sample sizes, VERBATIM from the ready-to-use
   sampling plan tables (Tables 43.01, 43.03, 43.05, 43.07). Eligibility
   (§41.01/§41.03) is returned as plain-language guidance strings, never
   silent logic — whether an agency may use a ready-to-use plan is a human
   determination.
2. **§83 APTL estimator** — sample APTL = sample total PMT ÷ sample total
   UPT (ratio of totals), annual PMT = 100% UPT expansion factor × sample
   APTL, with by-type-of-service-day variants. The input shape is per-unit
   (UPT, PMT) observation pairs and nothing else: a per-unit APTL is never
   computed, accepted, or exposed, so the §83.05(b)-banned average-of-ratios
   is UNCONSTRUCTIBLE through this API.
3. **Sample drawer** — seeded, deterministic, WITHOUT replacement, from a
   provided service-unit list (§63.03).

Regulatory basis — FTA NTD Sampling Manual, March 31, 2009
(docs/reference/The_NTD_Sampling_Manual.pdf), quoted verbatim in
REGULATORY_TRACKER.md, "Verified — NTD Sampling Manual" and "Sampling plan
tables — implementation quotes (sampling_v0)". The 2026 NTD Policy Manual
p. 150 names this manual as the FTA-approved sampling method source; no
newer edition exists to check against. No regulatory number in this module
comes from memory — every table cell below is a quoted cell of Tables
43.01–43.07, pinned one-for-one by tests/test_golden_sampling.py.

Key quoted rules (tracker section carries the full passages):

- **§41.01 (eligibility, guidance not logic):** ready-to-use plans are for a
  new mode, a new type of service, or "you have reported your service to the
  NTD before through random sampling, but no longer have the original raw
  sample data."
- **§41.03:** "You should not use it again if your next report year is your
  mandatory sampling year."
- **§63.03(b):** "You may use any other method for random sampling as long
  as it meets these two criteria: (1) sampling under the method is random.
  (2) sampling under the method is without replacement. Without replacement
  means that the method will not select the same service unit more than
  once."
- **§83.05(a):** "You must determine the sample APTL for a given sample as
  the ratio of sample total PMT over sample total UPT ..."
- **§83.05(b) — THE BAN:** "You must not determine the sample APTL as the
  average of the APTL across individual service units in the sample."
- **§83.01(a):** "You must use your 100% count of UPT as the expansion
  factor."
- **§83.07(a):** annual total PMT = sample APTL × the annual expansion
  factor (100% count of annual UPT), when the plan is not grouped.

Drawer procedure (documented per §63.03(b) — "any other method ... as long
as": random + without replacement): each service unit is keyed by
SHA-256(seed || "\\n" || unit_id); the frame is ordered by (key, unit_id)
and the first ``sample_size`` units are selected. With a seed produced by a
real randomness source (the caller's responsibility — Headway's API uses a
CSPRNG and RECORDS the seed on the plan), the induced ordering is random;
selection is without replacement BY CONSTRUCTION, because each unit appears
exactly once in the ordering and duplicate unit ids are refused. Given the
same (seed, frame) the draw reproduces bit-for-bit forever — the audit /
reproducibility requirement. This module itself never generates randomness
(headway_calc purity rule: no ``random``, no ``secrets``, no clock).

Estimation provenance: every estimator result carries the fixed
SAMPLING_ESTIMATION_METHOD label — a SAMPLED ESTIMATE, never conflated with
computed PMT (pmt_v0), never persisted to computed.metric_values.

Grouping option (§43.03(e)(1), §43.05) and Base-option estimation
(Section 70) are DEFERRED (handoff 0012, honest scope): the grouped table
cells are encoded and citable below, but grouped sampling/estimation must be
done "separately for individual route groups" (§43.05(a)) — not mechanized
in v0. The weighted-APTL steps (§83.05(c)) are v1.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. All arithmetic is Decimal; APTL is quantized to 0.01 (the
manual's own displayed precision — Table 83.01 shows 4.93; Exhibit 44 shows
4.71) and estimated PMT to whole passenger miles (the pmt_atl_estimate
convention), ROUND_HALF_EVEN.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable, Mapping, Sequence

CALC_NAME = "sampling_v0"
CALC_VERSION = "0.1.0"

#: Source pin for every citation string below.
MANUAL = (
    "FTA NTD Sampling Manual, March 31, 2009 (verified 2026-07-12, "
    "REGULATORY_TRACKER.md 'Verified — NTD Sampling Manual' / 'Sampling "
    "plan tables — implementation quotes')"
)

# ---------------------------------------------------------------------------
# Vocabulary (Table 41.01 — Options for Unit of Sampling and Measurement)
# ---------------------------------------------------------------------------

#: NTD mode code → ready-to-use plan mode group. §41.05: non-scheduled plans
#: exist for demand response (DR) and commuter vanpool (VP); scheduled plans
#: for bus (MB, TB), commuter rail (CR), and other rail (LR, HR, MR, AG).
MODE_GROUPS: Mapping[str, str] = {
    "DR": "demand_response",
    "VP": "commuter_vanpool",
    "MB": "bus",
    "TB": "bus",
    "CR": "commuter_rail",
    "LR": "other_rail",
    "HR": "other_rail",
    "MR": "other_rail",
    "AG": "other_rail",
}

#: Plain-language mode-group names for messages.
_GROUP_LABELS = {
    "demand_response": "demand response (DR)",
    "commuter_vanpool": "commuter vanpool (VP)",
    "bus": "bus (MB and TB)",
    "commuter_rail": "commuter rail (CR)",
    "other_rail": "other rail modes (LR, HR, MR, AG)",
}

#: Units of sampling and measurement per mode group (Table 41.01, quoted:
#: DR/commuter vanpool → "Vehicle days"; bus → "One-way trips, round trips";
#: CR → "One-way car trips"; other rail → "One-way car trips, one-way train
#: trips").
UNITS_BY_GROUP: Mapping[str, tuple[str, ...]] = {
    "demand_response": ("vehicle_days",),
    "commuter_vanpool": ("vehicle_days",),
    "bus": ("one_way_trips", "round_trips"),
    "commuter_rail": ("one_way_car_trips",),
    "other_rail": ("one_way_car_trips", "one_way_train_trips"),
}

UNIT_LABELS = {
    "vehicle_days": "vehicle days",
    "one_way_trips": "one-way trips",
    "round_trips": "round trips",
    "one_way_car_trips": "one-way car trips",
    "one_way_train_trips": "one-way train trips",
}

#: Efficiency options (§41.07(c)). 'aptl' is the APTL option WITHOUT route
#: grouping; 'aptl_grouped' (bus only) is the APTL option WITH route
#: grouping — its cells are encoded for citation completeness but grouped
#: sampling/estimation is deferred (see module docstring); 'base' samples
#: both UPT and PMT (Base-option ESTIMATION, Section 70, is deferred — the
#: sizes here are still the plan's requirement).
EFFICIENCY_OPTIONS = ("aptl", "aptl_grouped", "base")

#: Sampling frequencies (§41.07(d): "Three options are provided for sampling
#: frequency—quarterly, monthly, or weekly.").
FREQUENCIES = ("quarterly", "monthly", "weekly")

#: Periods per year for each frequency — calendar facts used only for
#: plain-language copy; the per-period AND annual sizes are both verbatim
#: table cells, never derived from one another.
PERIODS_PER_YEAR = {"quarterly": 4, "monthly": 12, "weekly": 52}

#: Service-day types for the §83.01(b)/§83.03(b) by-type-of-service-day
#: variants (the MR-20 / Exhibit 44 schedule-type vocabulary, minus the
#: 'Annual' rollup).
SERVICE_DAY_TYPES = ("Weekday", "Saturday", "Sunday")

# ---------------------------------------------------------------------------
# Eligibility and usage guidance — plain-language strings, NEVER silent logic
# ---------------------------------------------------------------------------

ELIGIBILITY_GUIDANCE: tuple[str, ...] = (
    (
        "Ready-to-use sampling plans may be used only under the §41.01 "
        "conditions — (a) New Mode: 'If you will be sampling and reporting "
        "for the first time this current report year for a particular mode "
        "that you do not already operate'; (b) New Type of Service: 'If you "
        "will be sampling and reporting this current report year for a "
        "particular type of service for the first time'; or (c) No Sample "
        "Data: 'If you have reported your service to the NTD before through "
        "random sampling, but no longer have the original raw sample data.' "
        "Headway records your plan; whether your agency meets one of these "
        "conditions is your determination. (" + MANUAL + ", §41.01, p. 3)"
    ),
    (
        "Reuse next year: 'You should not use it again if your next report "
        "year is your mandatory sampling year. After you have collected the "
        "sample data from this year, you should develop a template sampling "
        "plan with that sample data for your next report year.' You may "
        "reuse it only if next year is not a mandatory sampling year "
        "(§41.03(b)). Template plans (Section 50) are not yet mechanized in "
        "Headway. (" + MANUAL + ", §41.03, p. 3)"
    ),
    (
        "The estimate this plan supports must meet FTA's floor: 'Minimum "
        "confidence of 95 percent; and Minimum precision level of ±10 "
        "percent' — met by following the plan exactly: 'If a transit agency "
        "samples, they must follow the sampling technique exactly.' "
        "(2026 NTD Policy Manual, Full Reporting, p. 149 — verified "
        "2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger Miles "
        "Traveled')"
    ),
)

#: 2026 NTD Policy Manual p. 150 (tracker, 'Verified — Passenger Miles
#: Traveled': "documentation retained ≥3 years (p. 150)") — surfaced in API
#: and UI copy wherever sampling records are created or read.
RETENTION_NOTE = (
    "Keep every sampling record — the plan, the recorded seed, the drawn "
    "service-unit lists, and each unit's observed UPT and PMT — for at "
    "least 3 years (2026 NTD Policy Manual, Full Reporting, p. 150; "
    "verified 2026-07-12, REGULATORY_TRACKER.md 'Verified — Passenger "
    "Miles Traveled'). Headway keeps them indefinitely: sampling records "
    "are append-only and are corrected by superseding, never by editing."
)

#: §41.05(a) caveat, returned with every commuter-vanpool requirement.
_VANPOOL_CAVEAT = (
    "'You should not use the ready-to-use sampling plans for commuter "
    "vanpool if your vanpool service does not serve commuters exclusively.' "
    "(" + MANUAL + ", §41.05(a), p. 3)"
)

#: §43.03(e)(1) / §43.05(a) caveat on the grouped-APTL cells.
_GROUPING_CAVEAT = (
    "The With Route Grouping option requires you to 'divide your routes "
    "into two groups on the basis of route length and do sampling and "
    "estimation separately for each group' (§43.03(e)(1)) — 'You must do "
    "your sampling and estimation separately for individual route groups.' "
    "(§43.05(a)). Headway v0 does not mechanize per-group sampling or the "
    "§83.05(c) weighted-APTL estimation — this cell is provided for "
    "reference; use the Without Route Grouping option for a plan Headway "
    "can carry end-to-end. (" + MANUAL + ", pp. 5)"
)

#: Section 70 caveat on every base-option cell.
_BASE_CAVEAT = (
    "The Base Option samples BOTH UPT and PMT ('you must estimate both UPT "
    "and PMT through random sampling', §41.07(c)(1)). Headway v0 records "
    "the plan, the draw, and the measurements, but Base-option ESTIMATION "
    "(Section 70) is deferred — the §83 estimate endpoint serves the APTL "
    "option only. (" + MANUAL + ", §41.07(c), p. 4)"
)

# ---------------------------------------------------------------------------
# The ready-to-use sample-size tables — every cell VERBATIM
# ---------------------------------------------------------------------------
# Encoding: (mode_group, unit, option, frequency) →
#   (per_period, annual, table_id, column_label)
# per_period is the "<unit> for a <period>" row; annual is the "Total Sample
# Size for Year" row of the same table — BOTH are quoted cells (the manual
# prints both; they are not derived from each other here).

_T4301 = "Table 43.01. Ready-to-Use Sampling Plans for Non-Scheduled Services (p. 4)"
_T4303 = "Table 43.03. Ready-to-Use Sampling Plans for Bus (MB and TB) Services (p. 5)"
_T4305 = "Table 43.05. Ready-to-Use Sampling Plans for Commuter Rail (CR) (p. 6)"
_T4307 = "Table 43.07. Ready-to-Use Sampling Plans for Other Rail Modes (p. 6)"

_APTL_COL = "Reporting 100% UPT (APTL Option)"
_BASE_COL = "Not Reporting 100% UPT (Base Option)"
_APTL_GROUPED_COL = "Reporting 100% UPT (APTL Option) — With Route Grouping"
_APTL_UNGROUPED_COL = "Reporting 100% UPT (APTL Option) — Without Route Grouping"

_TABLE: dict[tuple[str, str, str, str], tuple[int, int, str, str]] = {
    # ----- Table 43.01 — Demand Response (DR), vehicle days ----------------
    ("demand_response", "vehicle_days", "aptl", "quarterly"): (12, 48, _T4301, _APTL_COL),
    ("demand_response", "vehicle_days", "aptl", "monthly"): (4, 48, _T4301, _APTL_COL),
    ("demand_response", "vehicle_days", "aptl", "weekly"): (1, 52, _T4301, _APTL_COL),
    ("demand_response", "vehicle_days", "base", "quarterly"): (22, 88, _T4301, _BASE_COL),
    ("demand_response", "vehicle_days", "base", "monthly"): (8, 96, _T4301, _BASE_COL),
    ("demand_response", "vehicle_days", "base", "weekly"): (2, 104, _T4301, _BASE_COL),
    # ----- Table 43.01 — Commuter Vanpool, vehicle days --------------------
    ("commuter_vanpool", "vehicle_days", "aptl", "quarterly"): (31, 124, _T4301, _APTL_COL),
    ("commuter_vanpool", "vehicle_days", "aptl", "monthly"): (10, 120, _T4301, _APTL_COL),
    ("commuter_vanpool", "vehicle_days", "aptl", "weekly"): (2, 104, _T4301, _APTL_COL),
    ("commuter_vanpool", "vehicle_days", "base", "quarterly"): (45, 180, _T4301, _BASE_COL),
    ("commuter_vanpool", "vehicle_days", "base", "monthly"): (15, 180, _T4301, _BASE_COL),
    ("commuter_vanpool", "vehicle_days", "base", "weekly"): (4, 208, _T4301, _BASE_COL),
    # ----- Table 43.03 — Bus (MB, TB), one-way trips ------------------------
    # §43.03(e)(1): grouped APTL = column (1); §43.03(e)(2): ungrouped APTL =
    # column (2); §43.03(d)(1): base = column (3).
    ("bus", "one_way_trips", "aptl_grouped", "quarterly"): (52, 208, _T4303, _APTL_GROUPED_COL + ", column (1)"),
    ("bus", "one_way_trips", "aptl_grouped", "monthly"): (18, 216, _T4303, _APTL_GROUPED_COL + ", column (1)"),
    ("bus", "one_way_trips", "aptl_grouped", "weekly"): (4, 208, _T4303, _APTL_GROUPED_COL + ", column (1)"),
    ("bus", "one_way_trips", "aptl", "quarterly"): (78, 312, _T4303, _APTL_UNGROUPED_COL + ", column (2)"),
    ("bus", "one_way_trips", "aptl", "monthly"): (27, 324, _T4303, _APTL_UNGROUPED_COL + ", column (2)"),
    ("bus", "one_way_trips", "aptl", "weekly"): (6, 312, _T4303, _APTL_UNGROUPED_COL + ", column (2)"),
    ("bus", "one_way_trips", "base", "quarterly"): (138, 552, _T4303, _BASE_COL + ", column (3)"),
    ("bus", "one_way_trips", "base", "monthly"): (46, 552, _T4303, _BASE_COL + ", column (3)"),
    ("bus", "one_way_trips", "base", "weekly"): (11, 572, _T4303, _BASE_COL + ", column (3)"),
    # ----- Table 43.03 — Bus (MB, TB), round trips ---------------------------
    # §43.03(e)(1): grouped APTL = column (4); §43.03(e)(2): ungrouped APTL =
    # column (5); §43.03(d)(2): base = column (6).
    ("bus", "round_trips", "aptl_grouped", "quarterly"): (39, 156, _T4303, _APTL_GROUPED_COL + ", column (4)"),
    ("bus", "round_trips", "aptl_grouped", "monthly"): (13, 156, _T4303, _APTL_GROUPED_COL + ", column (4)"),
    ("bus", "round_trips", "aptl_grouped", "weekly"): (3, 156, _T4303, _APTL_GROUPED_COL + ", column (4)"),
    ("bus", "round_trips", "aptl", "quarterly"): (59, 236, _T4303, _APTL_UNGROUPED_COL + ", column (5)"),
    ("bus", "round_trips", "aptl", "monthly"): (20, 240, _T4303, _APTL_UNGROUPED_COL + ", column (5)"),
    ("bus", "round_trips", "aptl", "weekly"): (5, 260, _T4303, _APTL_UNGROUPED_COL + ", column (5)"),
    ("bus", "round_trips", "base", "quarterly"): (103, 412, _T4303, _BASE_COL + ", column (6)"),
    ("bus", "round_trips", "base", "monthly"): (35, 420, _T4303, _BASE_COL + ", column (6)"),
    ("bus", "round_trips", "base", "weekly"): (8, 416, _T4303, _BASE_COL + ", column (6)"),
    # ----- Table 43.05 — Commuter Rail (CR), one-way car trips ---------------
    ("commuter_rail", "one_way_car_trips", "aptl", "quarterly"): (8, 32, _T4305, _APTL_COL),
    ("commuter_rail", "one_way_car_trips", "aptl", "monthly"): (3, 36, _T4305, _APTL_COL),
    ("commuter_rail", "one_way_car_trips", "aptl", "weekly"): (1, 52, _T4305, _APTL_COL),
    ("commuter_rail", "one_way_car_trips", "base", "quarterly"): (80, 320, _T4305, _BASE_COL),
    ("commuter_rail", "one_way_car_trips", "base", "monthly"): (27, 324, _T4305, _BASE_COL),
    ("commuter_rail", "one_way_car_trips", "base", "weekly"): (7, 364, _T4305, _BASE_COL),
    # ----- Table 43.07 — Other Rail Modes, one-way train trips ---------------
    ("other_rail", "one_way_train_trips", "aptl", "quarterly"): (6, 24, _T4307, "One-Way Train Trips — " + _APTL_COL),
    ("other_rail", "one_way_train_trips", "aptl", "monthly"): (2, 24, _T4307, "One-Way Train Trips — " + _APTL_COL),
    ("other_rail", "one_way_train_trips", "aptl", "weekly"): (1, 52, _T4307, "One-Way Train Trips — " + _APTL_COL),
    ("other_rail", "one_way_train_trips", "base", "quarterly"): (45, 180, _T4307, "One-Way Train Trips — " + _BASE_COL),
    ("other_rail", "one_way_train_trips", "base", "monthly"): (15, 180, _T4307, "One-Way Train Trips — " + _BASE_COL),
    ("other_rail", "one_way_train_trips", "base", "weekly"): (4, 208, _T4307, "One-Way Train Trips — " + _BASE_COL),
    # ----- Table 43.07 — Other Rail Modes, one-way car trips -----------------
    ("other_rail", "one_way_car_trips", "aptl", "quarterly"): (12, 48, _T4307, "One-Way Car Trips — " + _APTL_COL),
    ("other_rail", "one_way_car_trips", "aptl", "monthly"): (4, 48, _T4307, "One-Way Car Trips — " + _APTL_COL),
    ("other_rail", "one_way_car_trips", "aptl", "weekly"): (1, 52, _T4307, "One-Way Car Trips — " + _APTL_COL),
    ("other_rail", "one_way_car_trips", "base", "quarterly"): (72, 288, _T4307, "One-Way Car Trips — " + _BASE_COL),
    ("other_rail", "one_way_car_trips", "base", "monthly"): (24, 288, _T4307, "One-Way Car Trips — " + _BASE_COL),
    ("other_rail", "one_way_car_trips", "base", "weekly"): (6, 288, _T4307, "One-Way Car Trips — " + _BASE_COL),
}

_PERIOD_NOUN = {"quarterly": "Quarter", "monthly": "Month", "weekly": "Week"}


@dataclass(frozen=True)
class PlanRequirement:
    """One ready-to-use plan cell: what the manual requires, with citations.

    ``required_per_period`` and ``required_annual`` are BOTH verbatim table
    cells (the "<unit> for a <period>" row and the "Total Sample Size for
    Year" row). ``guidance`` carries §41.01/§41.03 eligibility plus any
    option-specific caveats — plain language for the plan wizard, never
    silent logic.
    """

    mode: str
    mode_group: str
    unit: str
    efficiency_option: str
    frequency: str
    required_per_period: int
    required_annual: int
    table: str
    column: str
    citation: str
    guidance: tuple[str, ...] = field(default_factory=tuple)
    selector_name: str = CALC_NAME
    selector_version: str = CALC_VERSION

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "mode_group": self.mode_group,
            "unit": self.unit,
            "efficiency_option": self.efficiency_option,
            "frequency": self.frequency,
            "required_per_period": self.required_per_period,
            "required_annual": self.required_annual,
            "table": self.table,
            "column": self.column,
            "citation": self.citation,
            "guidance": list(self.guidance),
            "selector_name": self.selector_name,
            "selector_version": self.selector_version,
        }


def plan_requirement(
    mode: str, unit: str, efficiency_option: str, frequency: str
) -> PlanRequirement:
    """Look up one ready-to-use plan cell, verbatim, with its citation.

    Raises ValueError with a plain-language message (listing the valid
    choices) for any input outside the tables — a sample size is never
    guessed, interpolated, or derived.
    """
    if mode not in MODE_GROUPS:
        raise ValueError(
            f"'{mode}' is not a mode the ready-to-use sampling plans cover. "
            f"Plans exist for: DR (demand response), VP (commuter vanpool), "
            f"MB/TB (bus), CR (commuter rail), and LR/HR/MR/AG (other rail) "
            f"— {MANUAL}, §41.05, p. 3."
        )
    group = MODE_GROUPS[mode]
    valid_units = UNITS_BY_GROUP[group]
    if unit not in valid_units:
        raise ValueError(
            f"'{unit}' is not a unit of sampling and measurement available "
            f"for {_GROUP_LABELS[group]}. Table 41.01 provides: "
            f"{', '.join(UNIT_LABELS[u] + ' (' + u + ')' for u in valid_units)} "
            f"— {MANUAL}, Table 41.01, p. 4."
        )
    if efficiency_option not in EFFICIENCY_OPTIONS:
        raise ValueError(
            f"'{efficiency_option}' is not an efficiency option. Choose "
            f"'aptl' (report a 100% UPT count and sample average passenger "
            f"trip length; for bus this is the Without Route Grouping "
            f"column), 'aptl_grouped' (bus only — With Route Grouping), or "
            f"'base' (sample both UPT and PMT) — {MANUAL}, §41.07(c), p. 4."
        )
    if frequency not in FREQUENCIES:
        raise ValueError(
            f"'{frequency}' is not a sampling frequency. Choose "
            f"'quarterly', 'monthly', or 'weekly' — {MANUAL}, §41.07(d), "
            f"p. 4."
        )
    key = (group, unit, efficiency_option, frequency)
    if key not in _TABLE:
        # Only one combination class remains representable-but-absent:
        # aptl_grouped outside bus.
        raise ValueError(
            f"The '{efficiency_option}' option does not exist for "
            f"{_GROUP_LABELS[group]}: route grouping is a bus (MB, TB) "
            f"option only ('Grouping Option – you must divide your bus "
            f"routes into two groups by route length', §41.07(c)(3)) — "
            f"{MANUAL}, p. 4."
        )
    per_period, annual, table, column = _TABLE[key]
    guidance = list(ELIGIBILITY_GUIDANCE)
    if group == "commuter_vanpool":
        guidance.append(_VANPOOL_CAVEAT)
    if efficiency_option == "aptl_grouped":
        guidance.append(_GROUPING_CAVEAT)
    if efficiency_option == "base":
        guidance.append(_BASE_CAVEAT)
    citation = (
        f"{table}, '{column}': {UNIT_LABELS[unit].capitalize()} for a "
        f"{_PERIOD_NOUN[frequency]} = {per_period}; Total Sample Size for "
        f"Year = {annual}. ({MANUAL})"
    )
    return PlanRequirement(
        mode=mode,
        mode_group=group,
        unit=unit,
        efficiency_option=efficiency_option,
        frequency=frequency,
        required_per_period=per_period,
        required_annual=annual,
        table=table,
        column=column,
        citation=citation,
        guidance=tuple(guidance),
    )


def all_table_cells() -> dict[tuple[str, str, str, str], tuple[int, int]]:
    """Every encoded (mode_group, unit, option, frequency) → (per-period,
    annual) cell — the goldens iterate this to guarantee no cell escapes
    pinning."""
    return {k: (v[0], v[1]) for k, v in _TABLE.items()}


# ---------------------------------------------------------------------------
# §83 APTL estimator — ratio of totals, average-of-ratios unconstructible
# ---------------------------------------------------------------------------

#: The provenance label every estimate carries. A SAMPLED ESTIMATE — never a
#: computed (measured) figure, never persisted to computed.metric_values.
SAMPLING_ESTIMATION_METHOD = (
    "estimated — sampled average passenger trip length (APTL) method (FTA "
    "NTD Sampling Manual, March 31, 2009, Subsection 83): sample APTL = "
    "sample total PMT ÷ sample total UPT (§83.05(a) ratio of totals); "
    "estimated PMT = 100% UPT expansion factor × sample APTL (§83.01(a), "
    "§83.07). Sample observations are manually entered ride-check data; "
    "this figure is a sampled ESTIMATE, not a computed PMT measurement."
)

#: §83.05(b), verbatim — pinned by tests/test_sampling.py. The input shape
#: below (per-unit UPT/PMT observation pairs only; no per-unit ratio is ever
#: computed, accepted, or exposed) makes the banned average-of-ratios
#: unconstructible through this API.
APTL_AVERAGE_OF_RATIOS_BAN = (
    "You must not determine the sample APTL as the average of the APTL "
    "across individual service units in the sample."
)

#: §83.05(a), verbatim.
APTL_RATIO_OF_TOTALS_RULE = (
    "You must determine the sample APTL for a given sample as the ratio of "
    "sample total PMT over sample total UPT"
)

#: APTL at the manual's displayed precision (Table 83.01: 4.93; Exhibit 44:
#: 4.71); estimates in whole passenger miles (the pmt_atl convention).
_APTL_QUANTUM = Decimal("0.01")
_ESTIMATE_QUANTUM = Decimal("1")


@dataclass(frozen=True)
class UnitObservation:
    """One sampled service unit's ride-check observation: the unit id and
    its observed totals. Deliberately carries NO ratio field — the §83.05(b)
    ban is enforced by construction.

    ``service_day_type`` is required only for the by-type-of-service-day
    estimate variants (Weekday / Saturday / Sunday).
    """

    unit_id: str
    observed_upt: int
    observed_pmt: Decimal
    service_day_type: str | None = None

    def __post_init__(self):
        if self.observed_upt < 0:
            raise ValueError(
                f"Observed UPT for unit {self.unit_id!r} must be zero or "
                f"more boardings; got {self.observed_upt}."
            )
        object.__setattr__(
            self, "observed_pmt", Decimal(str(self.observed_pmt))
        )
        if self.observed_pmt < 0:
            raise ValueError(
                f"Observed PMT for unit {self.unit_id!r} must be zero or "
                f"more passenger miles; got {self.observed_pmt}."
            )
        if self.service_day_type is not None and (
            self.service_day_type not in SERVICE_DAY_TYPES
        ):
            raise ValueError(
                f"'{self.service_day_type}' is not a service-day type; use "
                f"one of {SERVICE_DAY_TYPES}."
            )


@dataclass(frozen=True)
class SampledPmtEstimate:
    """One §83 APTL-option estimate with its full working and provenance.

    ``method`` is the fixed SAMPLING_ESTIMATION_METHOD label; the figure is
    a sampled ESTIMATE, never conflated with computed PMT.
    """

    scope: str  # 'annual' or a SERVICE_DAY_TYPES value
    sample_size: int
    sample_total_upt: int
    sample_total_pmt: Decimal
    sample_aptl: Decimal
    expansion_factor_upt: Decimal
    estimated_pmt: Decimal
    method: str = SAMPLING_ESTIMATION_METHOD

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "sample_size": self.sample_size,
            "sample_total_upt": self.sample_total_upt,
            "sample_total_pmt": str(self.sample_total_pmt),
            "sample_aptl": str(self.sample_aptl),
            "expansion_factor_upt": str(self.expansion_factor_upt),
            "estimated_pmt": str(self.estimated_pmt),
            "method": self.method,
        }


def sample_aptl(observations: Iterable[UnitObservation]) -> Decimal:
    """Sample APTL per §83.05(a): 'the ratio of sample total PMT over sample
    total UPT' — quantized 0.01 ROUND_HALF_EVEN (the manual's displayed
    precision). There is NO per-unit variant of this function: §83.05(b)
    bans the average of per-unit APTLs, so it cannot be built here.

    Refuses (ValueError) an empty sample or a sample with zero total UPT —
    a trip-length ratio over no passengers is a guess, never a figure.
    """
    observations = list(observations)
    if not observations:
        raise ValueError(
            "Cannot determine a sample APTL from an empty sample: no "
            "service units were observed."
        )
    total_upt = sum(o.observed_upt for o in observations)
    total_pmt = sum(o.observed_pmt for o in observations)
    if total_upt <= 0:
        raise ValueError(
            f"Cannot determine a sample APTL: the sample's total UPT is "
            f"{total_upt} (no passengers were observed across "
            f"{len(observations)} service unit(s)), so the §83.05(a) ratio "
            f"of sample total PMT over sample total UPT is undefined. "
            f"Individual zero-passenger units are fine — the ratio is over "
            f"TOTALS — but the whole sample cannot be passenger-free."
        )
    return (total_pmt / Decimal(total_upt)).quantize(
        _APTL_QUANTUM, rounding=ROUND_HALF_EVEN
    )


def estimate_annual_pmt(
    observations: Iterable[UnitObservation],
    annual_upt_100pct: Decimal | int | str,
) -> SampledPmtEstimate:
    """Annual total PMT per §83.07(a) (ungrouped plans): sample APTL for the
    entire annual sample × the annual expansion factor — §83.01(a): 'You
    must use your 100% count of UPT as the expansion factor.'

    The estimate is quantized to whole passenger miles, ROUND_HALF_EVEN.
    Refuses a non-positive expansion factor (a 100% UPT count of zero means
    there was no service to expand to — an estimate over it is a guess).
    """
    observations = list(observations)
    aptl = sample_aptl(observations)
    upt_100 = Decimal(str(annual_upt_100pct))
    if upt_100 <= 0:
        raise ValueError(
            f"The expansion factor must be a positive 100% count of UPT "
            f"(§83.01(a)); got {upt_100}."
        )
    return SampledPmtEstimate(
        scope="annual",
        sample_size=len(observations),
        sample_total_upt=sum(o.observed_upt for o in observations),
        sample_total_pmt=sum(
            (o.observed_pmt for o in observations), Decimal(0)
        ),
        sample_aptl=aptl,
        expansion_factor_upt=upt_100,
        estimated_pmt=(upt_100 * aptl).quantize(
            _ESTIMATE_QUANTUM, rounding=ROUND_HALF_EVEN
        ),
    )


def estimate_pmt_by_service_day(
    observations: Iterable[UnitObservation],
    upt_100pct_by_day_type: Mapping[str, Decimal | int | str],
) -> tuple[SampledPmtEstimate, ...]:
    """By-type-of-service-day estimates per §83.01(b)/§83.03(b)/§83.05(a)(2):
    within each service-day type, sample APTL = ratio of that day type's
    sample totals; estimated PMT = that day type's 100% UPT count × its
    sample APTL. Returns one estimate per day type present, in
    SERVICE_DAY_TYPES order.

    Refuses (ValueError): an observation without a service_day_type; a day
    type present in the sample but missing from ``upt_100pct_by_day_type``
    (an expansion factor is never guessed); unknown keys in the mapping;
    and the per-day-type degenerate cases sample_aptl refuses.
    """
    observations = list(observations)
    unknown = [
        k for k in upt_100pct_by_day_type if k not in SERVICE_DAY_TYPES
    ]
    if unknown:
        raise ValueError(
            f"Unknown service-day type key(s) {unknown} in the 100% UPT "
            f"counts; use {SERVICE_DAY_TYPES}."
        )
    unlabeled = [o.unit_id for o in observations if o.service_day_type is None]
    if unlabeled:
        raise ValueError(
            f"By-service-day estimation needs every observation labeled "
            f"with its service-day type (Weekday/Saturday/Sunday); "
            f"unlabeled unit(s): {', '.join(sorted(unlabeled))}. Label the "
            f"measurements or use the annual estimate."
        )
    estimates: list[SampledPmtEstimate] = []
    for day_type in SERVICE_DAY_TYPES:
        day_obs = [o for o in observations if o.service_day_type == day_type]
        if not day_obs:
            continue
        if day_type not in upt_100pct_by_day_type:
            raise ValueError(
                f"The sample contains {day_type} observations but no 100% "
                f"UPT count was supplied for {day_type} — the §83.01(b) "
                f"expansion factor ('use your annual total 100% count of "
                f"UPT by type of service days') is never guessed."
            )
        aptl = sample_aptl(day_obs)
        upt_100 = Decimal(str(upt_100pct_by_day_type[day_type]))
        if upt_100 <= 0:
            raise ValueError(
                f"The {day_type} expansion factor must be a positive 100% "
                f"count of UPT (§83.01(b)); got {upt_100}."
            )
        estimates.append(
            SampledPmtEstimate(
                scope=day_type,
                sample_size=len(day_obs),
                sample_total_upt=sum(o.observed_upt for o in day_obs),
                sample_total_pmt=sum(
                    (o.observed_pmt for o in day_obs), Decimal(0)
                ),
                sample_aptl=aptl,
                expansion_factor_upt=upt_100,
                estimated_pmt=(upt_100 * aptl).quantize(
                    _ESTIMATE_QUANTUM, rounding=ROUND_HALF_EVEN
                ),
            )
        )
    if not estimates:
        raise ValueError(
            "Cannot estimate by service-day type from an empty sample."
        )
    return tuple(estimates)


# ---------------------------------------------------------------------------
# Sample drawer — seeded, deterministic, WITHOUT replacement (§63.03)
# ---------------------------------------------------------------------------

#: The documented procedure (returned on every draw). §63.03(b), verbatim:
#: "You may use any other method for random sampling as long as it meets
#: these two criteria: (1) sampling under the method is random. (2) sampling
#: under the method is without replacement."
DRAW_METHOD = (
    "Keyed-hash random ordering (a §63.03(b) 'any other method'): each "
    "service unit in the provided list is keyed by SHA-256 of the recorded "
    "seed and the unit id; the list is ordered by key and the first n units "
    "are selected. With a seed produced by a cryptographic randomness "
    "source (recorded on the plan for audit), the ordering is random — "
    "§63.03(b)(1); each unit appears exactly once in the ordering and "
    "duplicate unit ids are refused, so no unit can be selected more than "
    "once — without replacement, §63.03(b)(2) ('Without replacement means "
    "that the method will not select the same service unit more than "
    "once.'). Given the same seed and the same unit list the draw "
    "reproduces exactly. (" + MANUAL + ", §63.03, p. 19)"
)


@dataclass(frozen=True)
class SampleDraw:
    """One reproducible draw: the selected units IN DRAW ORDER, the seed
    that produced them, and the documented §63.03 method."""

    selected_units: tuple[str, ...]
    seed: str
    sample_size: int
    frame_size: int
    method: str = DRAW_METHOD
    drawer_name: str = CALC_NAME
    drawer_version: str = CALC_VERSION

    def to_dict(self) -> dict:
        return {
            "selected_units": list(self.selected_units),
            "seed": self.seed,
            "sample_size": self.sample_size,
            "frame_size": self.frame_size,
            "method": self.method,
            "drawer_name": self.drawer_name,
            "drawer_version": self.drawer_version,
        }


def _draw_key(seed: str, unit_id: str) -> str:
    return hashlib.sha256(
        (seed + "\n" + unit_id).encode("utf-8")
    ).hexdigest()


def draw_sample(
    service_units: Sequence[str], sample_size: int, seed: str
) -> SampleDraw:
    """Draw ``sample_size`` units from ``service_units``, seeded and WITHOUT
    replacement (§63.03; procedure documented in DRAW_METHOD).

    Deterministic: the same (seed, unit list) reproduces the same selection
    in the same order regardless of the input list's ordering. This module
    never generates the seed — the caller must produce it from a real
    randomness source and RECORD it (Headway's API uses a CSPRNG and stores
    the seed on the plan).

    Refuses (ValueError): an empty seed; a non-positive sample size; a
    sample size larger than the list (without replacement makes that
    impossible — §63.03(b)(2)); duplicate unit ids (a duplicate could be
    'selected twice' under one identity — the frame must list each service
    unit exactly once).
    """
    if not seed:
        raise ValueError(
            "A draw needs a recorded seed (the reproducibility anchor); "
            "refusing to draw without one."
        )
    if sample_size < 1:
        raise ValueError(
            f"Sample size must be at least 1; got {sample_size}."
        )
    units = list(service_units)
    seen: set[str] = set()
    duplicates: list[str] = []
    for u in units:
        if u in seen:
            duplicates.append(u)
        seen.add(u)
    if duplicates:
        raise ValueError(
            f"The service-unit list contains duplicate unit id(s): "
            f"{', '.join(sorted(set(duplicates)))}. Each service unit must "
            f"appear exactly once — a duplicated id could be selected "
            f"more than once, violating without-replacement sampling "
            f"(§63.03(b)(2))."
        )
    if sample_size > len(units):
        raise ValueError(
            f"Cannot draw {sample_size} units without replacement from a "
            f"list of {len(units)}: without replacement, 'the method will "
            f"not select the same service unit more than once' "
            f"(§63.03(b)(2)), so the list must contain at least as many "
            f"units as the sample size."
        )
    ordered = sorted(units, key=lambda u: (_draw_key(seed, u), u))
    return SampleDraw(
        selected_units=tuple(ordered[:sample_size]),
        seed=seed,
        sample_size=sample_size,
        frame_size=len(units),
    )
