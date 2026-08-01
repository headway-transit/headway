"""revenue_window — the schedule-derived revenue-service window (handoff 0040).

A CORROBORATING signal for classifying no-run ("unassigned") boardings, never
the primary discriminator. The live diagnostic (2026-07-31) found the no-run
ghost boardings cluster hard at the START of the service day (the pre-service
hour has ~3x more ghost than real boardings) and the END (after the last
trip), and are sparse through midday: drivers/staff boarding during prep,
pull-out and pull-in. A vehicle not logged into a run is not in revenue
service (2026 NTD Policy Manual p. 128), so those boardings are not UPT.

The window derives from the GTFS schedule Headway ALREADY ingests — no new
ingestion (handoff 0040 design point 3). For one service date it is the
[first scheduled departure, last scheduled arrival] over the trips OPERATED
that day (the same operated-trips denominator the p. 146 missing-trip rule
uses), mapped to UTC through the agency's declared timezone. The GTFS "noon
minus 12 h" service-day anchor is DST-immune (the ops-calc precedent,
OPS_DEFINITIONS.md).

Why corroborating and not the rule: the PRIMARY discriminator is the no-run
assignment itself (the transform already decided this boarding resolved to no
run). The window only SPLITS the no-run boardings into the two cases the
handoff names:

- OUTSIDE the window (before the first departure or after the last arrival) —
  clearly prep / pull-out / pull-in, auto-classified NON-REVENUE and excluded
  from UPT with the reason recorded;
- INSIDE the window (mid-service) — genuinely ambiguous: it fits neither prep
  nor detour, and could be a real catch-up bus a dispatcher ran without a
  formal trip assignment (handoff 0040 design point 7). Auto-classifying it
  non-revenue would wrongly drop real riders, so it is held PENDING-REVIEW for
  a human, never silently counted and never silently excluded.

Pure and deterministic: stdlib only (``zoneinfo`` is stdlib), no clock reads,
no randomness. Time comes exclusively from the inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

#: Classification of a no-run event against the revenue window. The vocabulary
#: is the CORROBORATION, not the verdict — the verdict (non-revenue vs
#: pending-review) is upt_v0's, and it uses these to choose.
OUTSIDE_WINDOW = "outside_revenue_window"
INSIDE_WINDOW = "inside_revenue_window"
#: No window could be derived for the event's service date (no operated trips
#: with scheduled times, or no agency timezone) — the window signal is simply
#: absent and the no-run boarding is treated conservatively (see upt_v0).
NO_WINDOW = "no_revenue_window"


@dataclass(frozen=True)
class RevenueWindow:
    """One service date's revenue-service window, as UTC instants.

    ``first_departure`` / ``last_arrival`` are the earliest scheduled
    departure and latest scheduled arrival over the trips operated that day,
    both timezone-aware UTC. A single-timepoint day (only one bound present)
    still yields a usable window: the missing bound is None and the classifier
    treats an event beyond the present bound as outside.
    """

    service_date: date
    first_departure: datetime | None
    last_arrival: datetime | None

    def classify(self, event_time: datetime) -> str:
        """Where ``event_time`` (UTC) falls relative to this window.

        Before the first scheduled departure or after the last scheduled
        arrival is OUTSIDE (prep / pull-in); between them is INSIDE
        (mid-service, ambiguous). A window with neither bound present is
        NO_WINDOW — never a guess.
        """
        if self.first_departure is None and self.last_arrival is None:
            return NO_WINDOW
        if self.first_departure is not None and event_time < self.first_departure:
            return OUTSIDE_WINDOW
        if self.last_arrival is not None and event_time > self.last_arrival:
            return OUTSIDE_WINDOW
        return INSIDE_WINDOW


def scheduled_instant(service_date: date, seconds: int, zone: ZoneInfo) -> datetime:
    """UTC instant of a GTFS schedule time on one service date.

    GTFS convention (verify against the GTFS Schedule Reference, gtfs.org):
    schedule times are seconds after "noon minus 12 h" LOCAL of the service
    day — a DST-immune anchor. The same convention headway_calc.ops uses.
    """
    noon = datetime(
        service_date.year, service_date.month, service_date.day, 12, tzinfo=zone
    )
    return (noon - timedelta(hours=12) + timedelta(seconds=seconds)).astimezone(
        ZoneInfo("UTC")
    )


def build_windows(
    operated_stop_seconds: dict[date, tuple[int | None, int | None]],
    agency_timezone: str | None,
) -> dict[date, RevenueWindow]:
    """Build per-service-date revenue windows from scheduled stop seconds.

    ``operated_stop_seconds`` maps each service date to (min departure
    seconds, max arrival seconds) over that day's OPERATED trips' scheduled
    stop_times — the reader computes it in SQL so the calc stays pure over
    in-memory inputs. ``agency_timezone`` is the feed-declared zone
    (canonical.agencies); None (no zone on file, or more than one distinct
    zone, resolved by the caller) yields NO windows — a window is never
    anchored to a guessed zone.

    Returns one RevenueWindow per date with a usable bound; a date whose
    bounds are both absent is omitted (the classifier then reports NO_WINDOW
    for its events by absence).
    """
    if not agency_timezone:
        return {}
    zone = ZoneInfo(agency_timezone)
    windows: dict[date, RevenueWindow] = {}
    for service_date in sorted(operated_stop_seconds):
        first_seconds, last_seconds = operated_stop_seconds[service_date]
        if first_seconds is None and last_seconds is None:
            continue
        windows[service_date] = RevenueWindow(
            service_date=service_date,
            first_departure=(
                None
                if first_seconds is None
                else scheduled_instant(service_date, first_seconds, zone)
            ),
            last_arrival=(
                None
                if last_seconds is None
                else scheduled_instant(service_date, last_seconds, zone)
            ),
        )
    return windows
