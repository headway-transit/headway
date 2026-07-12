"""S&S-50 Non-Major Monthly Summary generator (handoff 0010) — NOT-REPORTABLE
preview, the mr20.py pattern.

Assembles, for one calendar month, the per-mode/per-type-of-service non-major
counts the S&S-50 requires, from safety.events joined to each event's LATEST
safety.event_classifications row (the sscls_v0 verdicts — this module never
classifies anything itself; an unclassified event is surfaced loudly, never
counted).

Regulatory basis (2026 S&S Policy Manual, verified 2026-07-12 —
REGULATORY_TRACKER.md, "Verified — Safety & Security reporting"):

- **Scope (p. 3):** the S&S-50 covers "injury-threshold events + non-major
  fires + non-major assaults on transit workers"; "Assaults on a transit
  worker do not require an injury to be reportable on the S&S-50."
- **Timing (p. 4 + Exhibit 3, p. 5):** submitted "for each mode and TOS …
  every month, even if no event occurs"; due end of the following month
  (January→Feb 28 … December→Jan 31). Zero-event months are therefore
  EXPLICIT ZERO ROWS here, one per operated mode — the trap the manual
  warns about.
- **CR/AR nuance (Exhibit 1, p. 3):** "CR and AR modes must only report
  non-major assaults on a transit worker." FLAGGED in the output, not
  silently applied (handoff 0010 design point 6): Headway's mode vocabulary
  is the transform's GTFS route_type map, and which of its modes correspond
  to NTD CR/AR is an unresolved agency-level mapping.

Binding rules (the mr20.py discipline):

- **NOT REPORTABLE.** reportable=false + banner, caveats enumerated
  programmatically.
- **Per-cell provenance:** every count carries the event_ids behind it.
- **Corrections:** a superseded event (superseded_by IS NOT NULL) is
  excluded from counts — its replacement row carries the truth — and its id
  is listed so the exclusion is visible.
- **Fail loudly:** events without a classification are never counted; their
  ids surface in ``unclassified_event_ids`` with a caveat.
- **Operated modes** derive exactly the way the per-mode calc path derives
  the mode dimension (handoff 0009): DISTINCT canonical.routes.mode LEFT
  JOINed onto the month's canonical.vehicle_positions via canonical.trips;
  a NULL mode buckets as 'unknown', never dropped, never guessed.

Pure and stdlib-only: takes any DB-API 2.0 connection (%s placeholders);
unit-testable with a fake connection. The CLI boundary
(``python -m headway_calc.ss50 --month 2026-06``) lives in headway_calc._cli
(ss50_main). Also here: ``build_ss40_export`` — the S&S-40 detail export per
major event (JSON with every met threshold's supporting fields; due date =
occurred_at + 30 days, Exhibit 2, p. 4).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from headway_calc.mr20 import month_period
from headway_calc.sscls import (
    MAJOR,
    NON_MAJOR,
    NOT_REPORTABLE,
)

GENERATOR_NAME = "headway_calc.ss50"
GENERATOR_VERSION = "0.1.0"

#: The unknown buckets — mode matches the per-mode calc convention
#: (headway_calc.mode.MODE_UNKNOWN); type of service has no telemetry source
#: yet, so an unentered TOS is bucketed, documented, and flagged.
MODE_UNKNOWN = "unknown"
TOS_UNKNOWN = "unknown"

BANNER = (
    "NOT REPORTABLE — preview package only. Every count below is governed "
    "by the caveats enumerated in 'caveats'; nothing in this package may be "
    "submitted to the NTD. Generated from safety.events joined to the "
    "latest sscls_v0 classification per event, with per-cell provenance "
    "(event_ids)."
)

_TRACKER_POINTER = (
    "2026 S&S Policy Manual, verified 2026-07-12 — "
    "services/calc/REGULATORY_TRACKER.md, 'Verified — Safety & Security "
    "reporting'"
)

CITATIONS = (
    {
        "id": "ss50_scope",
        "text": (
            "S&S-50 non-major scope (p. 3): injury-threshold events + "
            "non-major fires + non-major assaults on transit workers; "
            "'Assaults on a transit worker do not require an injury to be "
            "reportable on the S&S-50.'"
        ),
        "source": _TRACKER_POINTER,
    },
    {
        "id": "ss50_timing",
        "text": (
            "S&S-50 timing (p. 4 + Exhibit 3, p. 5): submitted 'for each "
            "mode and TOS … every month, even if no event occurs'; due end "
            "of the following month (January→Feb 28 … December→Jan 31)."
        ),
        "source": _TRACKER_POINTER,
    },
    {
        "id": "cr_ar_nuance",
        "text": (
            "Exhibit 1 (p. 3): 'CR and AR modes must only report non-major "
            "assaults on a transit worker.' FLAGGED, not applied — see "
            "caveat cr_ar_not_applied."
        ),
        "source": _TRACKER_POINTER,
    },
)

#: Latest classification per event for the month, half-open UTC on
#: occurred_at (the calc library's period convention). classification_id is
#: the deterministic tie-break; earlier classification rows are append-only
#: history.
_SELECT_MONTH_EVENTS_SQL = (
    "SELECT DISTINCT ON (e.event_id) e.event_id, e.occurred_at, e.mode, "
    "e.type_of_service, e.event_category, e.fatalities, e.injuries, "
    "e.assault_on_worker, e.superseded_by, c.classification, "
    "c.thresholds_met, c.classifier_version "
    "FROM safety.events AS e "
    "LEFT JOIN safety.event_classifications AS c ON c.event_id = e.event_id "
    "WHERE e.occurred_at >= %s AND e.occurred_at < %s "
    "ORDER BY e.event_id, c.classified_at DESC, c.classification_id DESC"
)

#: Operated modes for the month — the SAME derivation as the per-mode calc
#: path (handoff 0009 / headway_calc.reader): canonical.routes.mode LEFT
#: JOINed onto the month's vehicle positions via canonical.trips; NULL mode
#: buckets as 'unknown'.
SELECT_OPERATED_MODES_SQL = (
    "SELECT DISTINCT r.mode "
    "FROM canonical.vehicle_positions AS p "
    "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "WHERE p.time >= %s AND p.time < %s "
    "ORDER BY r.mode"
)

#: One event with its latest classification (the S&S-40 export source).
_SELECT_ONE_EVENT_SQL = (
    "SELECT e.event_id, e.occurred_at, e.mode, e.type_of_service, "
    "e.event_category, e.narrative, e.location, e.fatalities, e.injuries, "
    "e.property_damage_usd, e.serious_injury, e.substantial_damage, "
    "e.towed, e.evacuation_life_safety, e.assault_on_worker, "
    "e.involves_transit_vehicle, e.involves_second_rail_vehicle, "
    "e.grade_crossing, e.runaway_train, e.evacuation_to_rail_row, "
    "e.entered_by, e.entered_at, e.superseded_by, "
    "c.classification, c.thresholds_met, c.classifier_version, "
    "c.classified_at "
    "FROM safety.events AS e "
    "LEFT JOIN safety.event_classifications AS c ON c.event_id = e.event_id "
    "WHERE e.event_id = %s "
    "ORDER BY c.classified_at DESC, c.classification_id DESC "
    "LIMIT 1"
)


def ss50_due_date(month: str) -> date:
    """The S&S-50 due date for a month: the END of the FOLLOWING month
    (p. 4 + Exhibit 3, p. 5: January→Feb 28 … December→Jan 31)."""
    _, period_end = month_period(month)  # first day of the following month
    if period_end.month == 12:
        first_after = date(period_end.year + 1, 1, 1)
    else:
        first_after = date(period_end.year, period_end.month + 1, 1)
    return first_after - timedelta(days=1)


def _utc_midnights(period_start: date, period_end: date):
    return (
        datetime(period_start.year, period_start.month, period_start.day,
                 tzinfo=timezone.utc),
        datetime(period_end.year, period_end.month, period_end.day,
                 tzinfo=timezone.utc),
    )


def _empty_counts() -> dict:
    return {
        "injury_events": {"count": 0, "people_injured": 0, "event_ids": []},
        "non_major_fires": {"count": 0, "event_ids": []},
        "assaults_on_worker": {
            "count": 0,
            "without_injury": 0,
            "event_ids": [],
        },
    }


def build_ss50_package(conn, month: str) -> dict:
    """Assemble the S&S-50 preview package for one calendar month.

    Cells are keyed by (mode, type_of_service); a non-major event counts
    into its cell under the p. 3 scope rules; every operated mode with no
    countable events gets an EXPLICIT ZERO ROW ("even if no event occurs").
    Major, not-reportable, superseded, and unclassified events are excluded
    from counts and their ids listed. Deterministic: cells sorted by
    (mode, type_of_service), event_ids sorted, fixed caveat order. Does not
    write anything; transaction control stays with the caller.
    """
    period_start, period_end = month_period(month)
    start_dt, end_dt = _utc_midnights(period_start, period_end)

    cur = conn.cursor()
    cur.execute(_SELECT_MONTH_EVENTS_SQL, (start_dt, end_dt))
    event_rows = cur.fetchall()
    cur.execute(SELECT_OPERATED_MODES_SQL, (start_dt, end_dt))
    operated_modes = sorted(
        {(row[0] if row[0] is not None else MODE_UNKNOWN)
         for row in cur.fetchall()}
    )

    cells: dict[tuple[str, str], dict] = {}

    def _cell(mode: str, tos: str) -> dict:
        key = (mode, tos)
        if key not in cells:
            cells[key] = {
                "mode": mode,
                "type_of_service": tos,
                "zero_event": True,
                "counts": _empty_counts(),
            }
        return cells[key]

    major_ids: list[str] = []
    not_reportable_ids: list[str] = []
    superseded_ids: list[str] = []
    unclassified_ids: list[str] = []
    tos_unknown_seen = False

    for row in event_rows:
        (event_id, _occurred_at, mode, type_of_service, event_category,
         _fatalities, injuries, assault_on_worker, superseded_by,
         classification, _thresholds_met, _classifier_version) = row
        event_id = str(event_id)
        if superseded_by is not None:
            # The correction chain: only the latest (unsuperseded) row of a
            # chain carries the truth; the exclusion stays visible.
            superseded_ids.append(event_id)
            continue
        if classification is None:
            unclassified_ids.append(event_id)
            continue
        if classification == MAJOR:
            major_ids.append(event_id)
            continue
        if classification == NOT_REPORTABLE:
            not_reportable_ids.append(event_id)
            continue
        if classification != NON_MAJOR:
            raise ValueError(
                f"Event {event_id} carries unknown classification "
                f"{classification!r}; refusing to guess where it belongs."
            )

        tos = type_of_service if type_of_service else TOS_UNKNOWN
        if tos == TOS_UNKNOWN:
            tos_unknown_seen = True
        cell = _cell(mode, tos)
        cell["zero_event"] = False
        counts = cell["counts"]
        # The p. 3 scope, re-derived from the same fields the classifier's
        # non-major basis uses (safety.event_classifications stores the
        # verdict; the basis conditions are deterministic over the row).
        if injuries >= 1:
            counts["injury_events"]["count"] += 1
            counts["injury_events"]["people_injured"] += injuries
            counts["injury_events"]["event_ids"].append(event_id)
        if event_category == "fire":
            counts["non_major_fires"]["count"] += 1
            counts["non_major_fires"]["event_ids"].append(event_id)
        if assault_on_worker:
            counts["assaults_on_worker"]["count"] += 1
            if injuries == 0:
                counts["assaults_on_worker"]["without_injury"] += 1
            counts["assaults_on_worker"]["event_ids"].append(event_id)

    # Explicit zero rows: every operated mode with no cell yet ("even if no
    # event occurs"). TOS has no telemetry source — zero rows carry the
    # 'unknown' TOS bucket, flagged below.
    for mode in operated_modes:
        if not any(cell_mode == mode for cell_mode, _ in cells):
            _cell(mode, TOS_UNKNOWN)

    caveats: list[dict] = [
        {
            "id": "not_reportable_preview",
            "text": (
                "Preview only: Headway has no NTD-portal e-filing (format "
                "unverified, handoff 0010 design point 6); counts are "
                "assembled from manually entered events."
            ),
        },
        {
            "id": "cr_ar_not_applied",
            "text": (
                "Exhibit 1 (p. 3): 'CR and AR modes must only report "
                "non-major assaults on a transit worker.' NOT applied: "
                "which Headway modes correspond to NTD CR/AR is an "
                "unresolved agency-level mapping — cells for potentially "
                "CR/AR modes still show all non-major counts. Resolve the "
                "mode mapping before treating any cell as form-ready."
            ),
        },
        {
            "id": "tos_attribution",
            "text": (
                "Type of service (TOS) comes only from manual entry; "
                "operated-mode zero rows and events entered without a TOS "
                "carry the 'unknown' TOS bucket. The S&S-50 is per mode AND "
                "TOS (p. 4) — 'unknown' TOS cells are not form-ready."
            ),
        },
    ]
    if unclassified_ids:
        caveats.append(
            {
                "id": "unclassified_events",
                "text": (
                    f"{len(unclassified_ids)} event(s) in this month have "
                    f"no classification row and are NOT counted anywhere "
                    f"above — a missing verdict is never guessed. Classify "
                    f"them (sscls_v0) and regenerate."
                ),
            }
        )
    if superseded_ids:
        caveats.append(
            {
                "id": "superseded_excluded",
                "text": (
                    f"{len(superseded_ids)} superseded event(s) are "
                    f"excluded from counts; each correction's replacement "
                    f"row carries the truth (append-only corrections, "
                    f"migration 0017)."
                ),
            }
        )

    ordered_cells = [
        cells[key] for key in sorted(cells.keys())
    ]
    for cell in ordered_cells:
        for group in cell["counts"].values():
            group["event_ids"].sort()

    return {
        "form": "S&S-50",
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "month": month,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "period_convention": (
            "half-open [period_start, period_end), UTC, on occurred_at"
        ),
        "due_date": ss50_due_date(month).isoformat(),
        "reportable": False,
        "banner": BANNER,
        "citations": [dict(c) for c in CITATIONS],
        "caveats": caveats,
        "operated_modes": operated_modes,
        "cells": ordered_cells,
        "excluded": {
            "major_event_ids": sorted(major_ids),
            "not_reportable_event_ids": sorted(not_reportable_ids),
            "superseded_event_ids": sorted(superseded_ids),
            "unclassified_event_ids": sorted(unclassified_ids),
        },
    }


#: Supporting event fields per major threshold (the S&S-40 detail export:
#: "JSON with every threshold's supporting fields", handoff 0010).
_SUPPORTING_FIELDS_BY_THRESHOLD = {
    "fatality": ("fatalities",),
    "injury_immediate_transport": ("injuries",),
    "injury_two_or_more": ("injuries", "event_category"),
    "property_damage_25k": ("property_damage_usd",),
    "rail_serious_injury": ("serious_injury", "injuries"),
    # towed: a rail collision where any vehicle is towed away IS
    # substantial damage (Example 7C, tracker S&S addendum 2).
    "rail_substantial_damage": ("substantial_damage", "towed", "event_category"),
    "rail_to_rail_collision": (
        "event_category",
        "involves_second_rail_vehicle",
        "involves_transit_vehicle",
        "grade_crossing",
    ),
    "rail_collision_grade_crossing": ("event_category", "grade_crossing"),
    "rail_collision_vehicle_contact_assault": (
        "event_category",
        "involves_transit_vehicle",
    ),
    "collision_towaway": (
        "event_category",
        "involves_transit_vehicle",
        "towed",
    ),
    "evacuation_life_safety": ("evacuation_life_safety",),
    "rail_evacuation_to_row": ("evacuation_to_rail_row",),
    "derailment": ("event_category", "mode"),
    "runaway_train": ("runaway_train", "mode"),
    "cyber_substantial_damage": ("event_category", "substantial_damage"),
}


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def build_ss40_export(conn, event_id: str) -> dict:
    """The S&S-40 detail export for one event: the full event row, its
    latest classification, the due date (occurred_at + 30 days — Exhibit 2,
    p. 4: 'due no later than 30 days after the date of the event'), and
    every met threshold's supporting field values.

    Refuses (ValueError) an unknown event id. A non-major or unclassified
    event exports honestly with a note — nothing pretends to be an S&S-40
    obligation that is not one.
    """
    cur = conn.cursor()
    cur.execute(_SELECT_ONE_EVENT_SQL, (event_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(
            f"No safety event with id {event_id!r} exists; nothing to export."
        )

    columns = (
        "event_id", "occurred_at", "mode", "type_of_service",
        "event_category", "narrative", "location", "fatalities", "injuries",
        "property_damage_usd", "serious_injury", "substantial_damage",
        "towed", "evacuation_life_safety", "assault_on_worker",
        "involves_transit_vehicle", "involves_second_rail_vehicle",
        "grade_crossing", "runaway_train", "evacuation_to_rail_row",
        "entered_by", "entered_at", "superseded_by",
    )
    event = {
        name: _json_safe(value) for name, value in zip(columns, row[:23])
    }
    event["event_id"] = str(event["event_id"])
    if event["superseded_by"] is not None:
        event["superseded_by"] = str(event["superseded_by"])
    classification, thresholds_met, classifier_version, classified_at = row[23:27]

    occurred_at = row[1]
    due_date = (occurred_at + timedelta(days=30)).date()

    thresholds = []
    for threshold in list(thresholds_met or []):
        fields = _SUPPORTING_FIELDS_BY_THRESHOLD.get(threshold, ())
        thresholds.append(
            {
                "threshold": threshold,
                "supporting_fields": {f: event[f] for f in fields},
            }
        )

    notes = []
    if classification is None:
        notes.append(
            "This event has NO classification row — it is not (yet) an "
            "S&S-40 obligation; classify it (sscls_v0) first."
        )
    elif classification != MAJOR:
        notes.append(
            f"This event is classified {classification!r}, not 'major' — "
            f"it is NOT an S&S-40 obligation; the export is informational."
        )
    if event["superseded_by"] is not None:
        notes.append(
            "This event was corrected: its replacement (superseded_by) "
            "carries the truth; export the replacement instead."
        )

    return {
        "form": "S&S-40",
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "reportable": False,
        "banner": BANNER,
        "event": event,
        "classification": (
            None
            if classification is None
            else {
                "classification": classification,
                "thresholds_met": list(thresholds_met or []),
                "classifier_version": classifier_version,
                "classified_at": _json_safe(classified_at),
            }
        ),
        "thresholds": thresholds,
        "due": {
            "due_date": due_date.isoformat(),
            "citation": (
                "Exhibit 2, p. 4 — the S&S-40 is 'due no later than 30 "
                f"days after the date of the event.' ({_TRACKER_POINTER})"
            ),
        },
        "notes": notes,
    }


if __name__ == "__main__":  # pragma: no cover — process boundary
    from headway_calc._cli import ss50_main

    raise SystemExit(ss50_main())
