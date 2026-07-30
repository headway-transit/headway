"""Finding-title vocabulary helpers (handoff 0032). Stdlib only, pure.

WHY THIS MODULE EXISTS
----------------------
First-agency UAT, on a live telemetry-gap warning: findings should show
**what vehicle and route** they concern. What Headway titled that finding
was *"Group excluded over telemetry gap of 731s: vehicle 07b5efcb-… trip
f3a4a888-…"* — machine identity where a dispatcher scans for route,
vehicle, when. This module renders titles in that order:

    Route 42, vehicle 5335: 12-minute telemetry silence (22:41–22:53 Jul 28)

and falls back HONESTLY when a part is unknown — a shortened opaque id when
the feed broadcast no fleet label, no route at all when the trip is
unresolvable. A label is never invented (handoff 0029 rule 2); the full raw
identifiers stay in the finding's description and subject, because internal
ids are the provenance — the footnote, not the headline.

The calc stays pure: every function here formats values it is GIVEN
(vehicle_label and route_short_name travel with the input rows —
VehiclePosition, handoff 0032); nothing queries, nothing looks up.

Conventions, each deliberate:

- **Durations ≥ 120 s render in minutes** ("12-minute", rounded to the
  nearest whole minute) — a dispatcher reads "12-minute", not "731s". The
  exact seconds remain in the description, which is why the title may
  round. Below 120 s, whole seconds ("90-second") — "1-minute" would hide
  the size of a sub-threshold-looking number.
- **Times are UTC with the date** ("22:41–22:53 Jul 28"), exactly as the
  descriptions already state them in ISO form — local-time display is the
  UI's job, and a title that silently localized would contradict its own
  description.
- **Opaque ids are shortened for the title only** (first 8 characters +
  '…') and only when actually long: an agency whose vehicle ids ARE its
  fleet numbers ('y1747', 'G-10099') keeps them whole.

Not a public API; the calculation modules remain the versioned surface.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable

from headway_calc.types import VehiclePosition, VehicleRef

#: Ids longer than this are shortened in TITLES (descriptions and subjects
#: always carry the full id). 16 keeps every fleet-style id ('y1747',
#: 'G-10099', '5335') whole while folding UUIDs.
_SHORT_ID_MAX = 16

#: How many leading characters of a long id survive in a title. Eight hex
#: characters is the conventional short form of a content hash/UUID and is
#: unambiguous within any one agency's fleet.
_SHORT_ID_KEEP = 8

#: The seconds line above which a title speaks minutes. Two minutes: below
#: it, rounding to minutes would render '1-minute' or '0-minute' and hide
#: the actual size.
_MINUTES_FLOOR_SECONDS = 120.0

#: How many distinct route names a title lists before summarizing the rest
#: as a count — a title is a headline, not an inventory (the stated-cap
#: discipline of handoff 0029).
_ROUTES_IN_TITLE_CAP = 3


def short_id(raw: str) -> str:
    """A title-sized rendering of an identifier.

    Returned whole when short (fleet-style ids stay recognizable); folded
    to its first 8 characters + '…' when long (UUIDs). Titles only — the
    full id always remains in the description and the subject ids.
    """
    if len(raw) <= _SHORT_ID_MAX:
        return raw
    return raw[:_SHORT_ID_KEEP] + "…"


def vehicle_handle(vehicle_id: str, label: str | None) -> str:
    """The vehicle as dispatch names it: the feed's label when one exists,
    the (shortened) feed id when none does. Nothing is invented — an
    unlabeled vehicle is honestly its id."""
    if label:
        return f"vehicle {label}"
    return f"vehicle {short_id(vehicle_id)}"


def group_vehicle_ref(
    vehicle_id: str, positions: Iterable[VehiclePosition]
) -> VehicleRef:
    """The VehicleRef of one finding's group, from the rows the calc was
    GIVEN (purity: no lookup). The label is the latest non-None
    vehicle_label in the given (time-ordered) positions — deterministic,
    and correct when a mid-period feed change starts broadcasting labels;
    None when no position carries one."""
    label: str | None = None
    for pos in positions:
        if pos.vehicle_label is not None:
            label = pos.vehicle_label
    return VehicleRef(vehicle_id=vehicle_id, label=label)


def route_names(positions: Iterable[VehiclePosition]) -> tuple[str, ...]:
    """The distinct route short names present in the given rows, sorted —
    empty when none is known (the title then omits the route entirely
    rather than showing an opaque route_id)."""
    names = {
        pos.route_short_name
        for pos in positions
        if pos.route_short_name is not None
    }
    return tuple(sorted(names))


def subject_phrase(
    routes: tuple[str, ...], vehicle_id: str, label: str | None
) -> str:
    """The title's opening — route(s) then vehicle, the order a dispatcher
    scans (handoff 0032): 'Route 42, vehicle 5335'. With no known route,
    the vehicle leads capitalized: 'Vehicle 5335'. More than
    3 routes are summarized as a stated count, never silently dropped."""
    handle = vehicle_handle(vehicle_id, label)
    if not routes:
        return handle[0].upper() + handle[1:]
    if len(routes) == 1:
        return f"Route {routes[0]}, {handle}"
    shown = routes[:_ROUTES_IN_TITLE_CAP]
    if len(routes) <= _ROUTES_IN_TITLE_CAP:
        return f"Routes {', '.join(shown)}, {handle}"
    return (
        f"Routes {', '.join(shown)} and {len(routes) - len(shown)} more, "
        f"{handle}"
    )


def duration_phrase(seconds: float) -> str:
    """'12-minute' for ≥ 120 s (nearest whole minute — the exact seconds
    stay in the description), '90-second' below."""
    if seconds >= _MINUTES_FLOOR_SECONDS:
        return f"{round(seconds / 60)}-minute"
    return f"{seconds:.0f}-second"


def _hm(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _day(dt: datetime) -> str:
    return f"{dt.strftime('%b')} {dt.day}"


def day_phrase(when: datetime | date) -> str:
    """One calendar day, UTC, as a title reads it: 'Jul 28'."""
    if isinstance(when, datetime):
        when = when.astimezone(timezone.utc).date()
    return f"{when.strftime('%b')} {when.day}"


def window_phrase(start: datetime, end: datetime) -> str:
    """A UTC time window with its date: '22:41–22:53 Jul 28', or, across
    midnight, '23:58 Jul 28–00:13 Jul 29' — the date is never dropped from
    either side of a boundary the reader could misplace."""
    s = start.astimezone(timezone.utc)
    e = end.astimezone(timezone.utc)
    if s.date() == e.date():
        return f"{_hm(s)}–{_hm(e)} {_day(s)}"
    return f"{_hm(s)} {_day(s)}–{_hm(e)} {_day(e)}"
