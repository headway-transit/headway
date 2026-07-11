"""MR-20 package generator (handoff 0009) — NOT-REPORTABLE preview.

Assembles the four MR-20 data points per mode (plus fleet totals) from
computed.metric_values into one package dict/JSON — the artifact the web
report view can later consume verbatim.

Regulatory basis (2025 NTD Monthly and Weekly Reference Policy Manual, Form
MR-20, manual pp. 32–33, verified 2026-07-11 — REGULATORY_TRACKER.md,
"Verified — Monthly Ridership form MR-20"): "The MR-20 form requires
agencies to report the following data points: • Unlinked Passenger Trips
(UPT) • Actual Vehicle (Passenger Car) Revenue Hours • Actual Vehicle
(Passenger Car) Revenue Miles • Vehicles Operated in Annual Maximum Service
(VOMS)", reported "for each mode of public transportation service that the
agency operates" (p. 32).

Binding rules:

- **NOT REPORTABLE.** Every package carries reportable=false and a banner;
  the governing caveats are enumerated PROGRAMMATICALLY: the fixed
  divergence list D1–D6 (tracker "Divergence analysis") plus caveats derived
  from the flags actually present in the assembled cells (pre-verification
  calc versions, simulated source data, the voms_v0 proxy divergences,
  partial VOMS observation, rail modes pending D2, missing cells).
- **Missing cell = explicit null + reason, never invented.** A metric/scope
  with no computed.metric_values row appears as {"value": null, "reason":
  ...} — a blocked or never-run figure is reported as missing.
- **Rail modes are flagged non-reportable pending D2** (rail passenger-car
  measure). The rail mode strings come from the transform's GTFS
  route_type→mode map (headway_transform.gtfs_static.ROUTE_TYPE_TO_MODE):
  the rail-running modes are 'tram' (0), 'subway' (1), 'rail' (2),
  'cable_tram' (5), 'funicular' (7) and 'monorail' (12).
- **Latest per metric+scope+period:** for each (metric, scope) the newest
  computed_at row (metric_value_id as deterministic tie-break) is the cell's
  source — earlier rows remain in the table untouched (append-only history).

Pure and stdlib-only: takes any DB-API 2.0 connection (%s placeholders);
unit-testable with a fake connection. The CLI process boundary
(``python -m headway_calc.mr20 --month 2026-07``) lives in
headway_calc._cli (mr20_main).
"""

from __future__ import annotations

import json
from datetime import date

#: The four MR-20 data points (p. 32 quote above), in form order.
MR20_METRICS = ("upt", "vrh", "vrm", "voms")

GENERATOR_NAME = "headway_calc.mr20"
GENERATOR_VERSION = "0.1.0"

#: Rail-running mode strings per the transform's GTFS route_type→mode map
#: (headway_transform.gtfs_static.ROUTE_TYPE_TO_MODE — route_types 0, 1, 2,
#: 5, 7, 12). Divergence D2 (rail passenger-car measure — a 4-car train is 4
#: passenger-car revenue miles, 2026 NTD Policy Manual p. 129) makes these
#: modes non-reportable until consist data exists.
RAIL_MODES = frozenset(
    {"tram", "subway", "rail", "cable_tram", "funicular", "monorail"}
)

#: The fixed divergence list (tracker "Divergence analysis", 2026-07-10) —
#: ALWAYS enumerated: these govern every position-derived figure regardless
#: of which cells are present.
_FIXED_DIVERGENCE_CAVEATS = (
    {
        "id": "D1",
        "status": "closed",
        "text": (
            "Layover/recovery time in VRH — CLOSED by vrh_v0 0.3.0/0.4.0 "
            "block-aware layover inclusion (tracker); retained here because "
            "the closure is calc-version-specific."
        ),
    },
    {
        "id": "D2",
        "status": "open",
        "text": (
            "Rail passenger-car measure: rail VRM/VRH/VOMS count passenger "
            "cars (a 4-car train x 1 mi = 4 car-miles); GTFS-RT carries one "
            "vehicle per trainset. Rail modes are flagged non-reportable "
            "pending consist data."
        ),
    },
    {
        "id": "D3",
        "status": "open",
        "text": (
            "Revenue-service proxy: trip_id assignment stands in for 'in "
            "revenue service'; agency practice varies — per-agency "
            "confirmation required."
        ),
    },
    {
        "id": "D4",
        "status": "open",
        "text": (
            "Measurement fidelity: position-derived haversine distance "
            "chord-cuts curves; validate against odometer/shape distance "
            "before reportability."
        ),
    },
    {
        "id": "D5",
        "status": "open",
        "text": (
            "Demand-response definition (first pick-up to last drop-off) is "
            "not implemented; DR is out of scope for the fixed-route calcs."
        ),
    },
    {
        "id": "D6",
        "status": "open",
        "text": (
            "Excluded activities (charter/school/training/maintenance) are "
            "excluded only insofar as they carry no trip_id (covered by the "
            "D3 proxy caveat)."
        ),
    },
)

#: Flag-conditional caveats, keyed by the cell flag that triggers them.
_CAVEAT_BY_FLAG = {
    "pre_verification": (
        "One or more figures come from 0.x (pre-verification) calc versions: "
        "definitions are verified against the NTD manuals but the "
        "implementations carry documented divergences (REGULATORY_TRACKER.md) "
        "— no 0.x figure is reportable."
    ),
    "simulated_source_data": (
        "One or more figures consumed SIMULATED source records (e.g. "
        "source='tides_simulated'): a certifiable figure containing simulated "
        "records is a contradiction (handoff-0005 simulated-data rule)."
    ),
    "voms_day_level_proxy": (
        "VOMS is the voms_v0 day-level proxy: the maximum over service days "
        "(UTC) of distinct vehicles observed in revenue service — an "
        "UPPER-BOUND proxy for the p. 33 'maximum service requirement' "
        "(schedule-peak simultaneity); the atypical-day exclusion is NOT "
        "implemented (agency calendar policy pending); rail passenger-car "
        "counting pending D2 (tracker, calc voms_v0 divergences a/b/c)."
    ),
    "voms_partial_observation": (
        "One or more VOMS figures observed fewer days than the period "
        "contains (voms_partial_observation warning): the reported maximum "
        "may understate the month's true VOMS."
    ),
    "uncertified": (
        "One or more figures carry certification_status 'uncertified': no "
        "human attestation exists for them (cert.certifications)."
    ),
}

_MISSING_CELL_CAVEAT = (
    "One or more cells are missing (value null with a reason): the metric was "
    "not computed for that scope, or its run was blocked by dq findings — a "
    "missing figure is reported as missing, never invented."
)

BANNER = (
    "NOT REPORTABLE — preview package only. Every figure below is governed "
    "by the caveats enumerated in 'caveats'; nothing in this package may be "
    "submitted to the NTD. Generated from computed.metric_values with full "
    "provenance (metric_value_id, calc_version, certification_status, flags, "
    "coverage) per cell."
)

#: Latest row per (metric, scope) for the exact period: newest computed_at,
#: metric_value_id as the deterministic tie-break. Earlier rows are history.
_SELECT_LATEST_SQL = (
    "SELECT DISTINCT ON (metric, scope) metric, scope, metric_value_id, "
    "value, unit, calc_name, calc_version, certification_status, detail "
    "FROM computed.metric_values "
    "WHERE period_start = %s AND period_end = %s "
    "AND metric IN ('upt', 'vrh', 'vrm', 'voms') "
    "ORDER BY metric, scope, computed_at DESC, metric_value_id DESC"
)


def month_period(month: str) -> tuple[date, date]:
    """'YYYY-MM' → the half-open calendar-month period [start, end).

    Mirrors the calc library's period convention (UTC, half-open): the July
    2026 package covers [2026-07-01, 2026-08-01). Refuses (ValueError) a
    string that is not exactly YYYY-MM.
    """
    parts = month.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError(
            f"month must be 'YYYY-MM' (e.g. '2026-07'); got {month!r}"
        )
    year, month_number = int(parts[0]), int(parts[1])
    start = date(year, month_number, 1)  # ValueError on a bad month number
    end = (
        date(year + 1, 1, 1)
        if month_number == 12
        else date(year, month_number + 1, 1)
    )
    return start, end


def _parse_detail(detail) -> dict:
    """detail arrives as a dict (psycopg JSONB) or JSON text (other drivers/
    fakes); anything else is refused loudly."""
    if detail is None:
        return {}
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        return json.loads(detail)
    raise TypeError(f"Unsupported detail payload type: {type(detail).__name__}")


def _cell_flags(metric: str, calc_version: str, certification_status: str, detail: dict) -> list[str]:
    """Provenance flags for one cell, derived from FACTS in the row — never
    guessed. Sorted for determinism."""
    flags: set[str] = set()
    if calc_version.startswith("0."):
        flags.add("pre_verification")
    if certification_status != "certified":
        flags.add("uncertified")
    source_mix = detail.get("source_mix")
    if isinstance(source_mix, dict) and any(s != "tides" for s in source_mix):
        flags.add("simulated_source_data")
    if metric == "voms":
        flags.add("voms_day_level_proxy")
        days_observed = detail.get("days_observed")
        days_in_period = detail.get("days_in_period")
        if (
            isinstance(days_observed, int)
            and isinstance(days_in_period, int)
            and days_observed < days_in_period
        ):
            flags.add("voms_partial_observation")
    return sorted(flags)


def _cell(row) -> dict:
    """One MR-20 cell from one computed.metric_values row."""
    metric, _scope, metric_value_id, value, unit, calc_name, calc_version, certification_status, detail = row
    detail_dict = _parse_detail(detail)
    return {
        "value": str(value),
        "unit": unit,
        "metric_value_id": str(metric_value_id),
        "calc_name": calc_name,
        "calc_version": calc_version,
        "certification_status": certification_status,
        "flags": _cell_flags(metric, calc_version, certification_status, detail_dict),
        # vrm/vrh carry a coverage ratio in detail; upt (missing_share) and
        # voms (days_observed) evidence completeness differently — null, not
        # a guessed ratio.
        "coverage": detail_dict.get("coverage"),
    }


def _missing_cell(metric: str, scope: str, period_start: date, period_end: date) -> dict:
    return {
        "value": None,
        "reason": (
            f"No computed.metric_values row for metric {metric!r} scope "
            f"{scope!r} in period [{period_start.isoformat()}, "
            f"{period_end.isoformat()}): the metric was not computed for "
            f"this scope, or its run was blocked (see dq.issues). A missing "
            f"figure is reported as missing, never invented."
        ),
    }


def build_mr20_package(conn, month: str) -> dict:
    """Assemble the MR-20 preview package for one calendar month.

    Reads the latest computed.metric_values row per (metric, scope) for the
    month's half-open period and mirrors the four MR-20 data points per mode
    (scopes 'mode:<mode>') plus fleet totals (scope 'agency'). Each present
    cell carries {value, unit, metric_value_id, calc_name, calc_version,
    certification_status, flags, coverage}; each absent cell is an explicit
    null + reason. Rail modes (RAIL_MODES — the transform's route_type map)
    carry non_reportable_pending_d2=true. The header is the NOT-REPORTABLE
    banner plus the programmatically enumerated caveats (fixed D-list +
    flag-derived). Deterministic: sorted modes, sorted flags, fixed caveat
    order (flag-derived caveats in flag-name order, then missing-cell, then
    D1–D6).

    Does not write anything; transaction control stays with the caller.
    """
    period_start, period_end = month_period(month)
    cur = conn.cursor()
    cur.execute(_SELECT_LATEST_SQL, (period_start, period_end))
    rows = cur.fetchall()

    cells_by_scope: dict[str, dict[str, dict]] = {}
    for row in rows:
        metric, scope = row[0], row[1]
        cells_by_scope.setdefault(scope, {})[metric] = _cell(row)

    mode_scopes = sorted(s for s in cells_by_scope if s.startswith("mode:"))
    modes = [s.split(":", 1)[1] for s in mode_scopes]

    any_missing = False
    flags_present: set[str] = set()

    def _scope_cells(scope: str) -> dict:
        nonlocal any_missing
        cells: dict[str, dict] = {}
        present = cells_by_scope.get(scope, {})
        for metric in MR20_METRICS:
            if metric in present:
                cells[metric] = present[metric]
                flags_present.update(present[metric]["flags"])
            else:
                cells[metric] = _missing_cell(metric, scope, period_start, period_end)
                any_missing = True
        return cells

    modes_out: dict[str, dict] = {}
    for mode in modes:
        entry = _scope_cells(f"mode:{mode}")
        entry["non_reportable_pending_d2"] = mode in RAIL_MODES
        modes_out[mode] = entry
    fleet = _scope_cells("agency")

    caveats: list[dict] = [
        {"id": f"flag:{flag}", "status": "open", "text": _CAVEAT_BY_FLAG[flag]}
        for flag in sorted(flags_present)
        if flag in _CAVEAT_BY_FLAG
    ]
    if any_missing:
        caveats.append(
            {"id": "missing_cells", "status": "open", "text": _MISSING_CELL_CAVEAT}
        )
    caveats.extend(dict(c) for c in _FIXED_DIVERGENCE_CAVEATS)

    return {
        "form": "MR-20",
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "month": month,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_convention": "half-open [period_start, period_end), UTC",
        "citation": (
            "2025 NTD Monthly and Weekly Reference Policy Manual, Monthly "
            "Ridership Reporting (Form MR-20), pp. 32-33 — verified "
            "2026-07-11 (REGULATORY_TRACKER.md, 'Verified — Monthly "
            "Ridership form MR-20')"
        ),
        "reportable": False,
        "banner": BANNER,
        "caveats": caveats,
        "data_points": list(MR20_METRICS),
        "modes": modes_out,
        "fleet": fleet,
    }


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import mr20_main

    raise SystemExit(mr20_main())
