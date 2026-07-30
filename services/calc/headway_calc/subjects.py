"""Resolving a Finding's subject into the agency's own vocabulary
(handoff 0029).

WHY THIS MODULE EXISTS
----------------------
A finding is addressed to a person who has to go fix something. It must name
the thing in the vocabulary that person uses to find it. The first agency to
run UAT said it plainly: *"staff/users will need an easier way to know what
exact block they are looking for that had the issue."* What Headway showed
him was a wall of opaque ids.

The calculation library cannot fix that by itself, and must not try: it is
PURE — no network, no clock, no database — so it has no route names, no
blocks, no departure times. What it knows is exactly WHICH canonical rows a
finding is about, and it says so with a
:class:`~headway_calc.types.SubjectRef`. This module is the other half: at
PERSISTENCE time, where a repository connection already exists, it resolves
those ids into the labels an agency actually uses and hands the result to
headway_calc.dq to freeze on the dq.issues row.

THE THREE RULES THIS MODULE OBEYS
---------------------------------
1. **Resolved once, frozen forever.** The labels are written alongside the
   ids at issue-creation time and never recomputed. A finding therefore
   reads in an audit years later exactly as it read the day it was raised,
   even after the agency renames a route or the feed drops a block. The ids
   stay too, so any reader can re-derive.
2. **No label is ever invented.** A trip with no block shows no block; a
   route with no short name shows no short name; a trip Headway never saw in
   canonical.trips is reported as exactly that. Absent data renders as
   absent — never as a guess, a placeholder, or a plausible-looking
   substitute.
3. **Grouping is the feature.** 1,111 individually listed trip ids help
   nobody. Trips are grouped BY BLOCK, each group carrying its trip count,
   the route(s) involved and the span from first to last scheduled
   departure. A dispatcher recognises "18 trips, Route 42, 06:14–14:22" as a
   block even when its id is a UUID.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No agency block-label mapping (feed ``block_id`` → operational name like
``225-4``). The partner agency's feed carries opaque UUIDs in ``block_id``,
so no display change can turn one into ``225-4`` — the names are not in the
data. The right fix is their GTFS export emitting the operational name in
``block_id``, which costs them one export setting and benefits every
downstream consumer. A Headway-side mapping table is a permanent maintenance
burden adopted to work around a one-line export change, and is recorded as
an open question rather than built.

Also not here: **trip headsign.** The handoff lists it as an available
label, but ``canonical.trips`` carries no headsign column and the transform
never maps one — the field does not exist anywhere in Headway today.
Inventing one is exactly what rule 2 forbids, and adding it means a
canonical-model change in the transform service (out of this wave's scope),
so headsign is absent from every context this module builds. Recorded as a
follow-up, not faked.

Impurity is intentional and contained: this module takes a DB-API 2.0
connection and issues SELECTs. It lives beside headway_calc.reader (the
other impure member of the package) precisely so the calculations
themselves stay pure. It never writes.
"""

from __future__ import annotations

from headway_calc.types import SUBJECT_KINDS, SUBJECT_TRIPS, Finding, SubjectRef

#: Schema version of the stored context blob (dq.issues.subject_context).
#: A reader that does not recognise the version must render the finding as
#: if there were no context at all, exactly as a pre-0035 row renders —
#: which is why the version is the first key anyone looks at.
CONTEXT_VERSION = 1

#: How many GROUPS are materialised into the stored context. A blocking
#: finding over a whole month can touch thousands of blocks; writing them
#: all would turn a readable finding back into a wall. The cap is STATED
#: (``group_count`` carries the true total, ``group_cap`` the cap) — nothing
#: is silently dropped, and the complete id list is always recoverable from
#: the calculation, because the calc emits every id.
GROUP_CAP = 25

#: How many raw trip ids each materialised group carries for the "technical
#: detail" disclosure. The group's ``trip_count`` always states the true
#: total, so a truncated sample can never be mistaken for the whole.
TRIP_IDS_PER_GROUP_CAP = 20

#: How many distinct routes a group names before truncating (``route_count``
#: states the true total). Blocks normally run one or two routes; a long tail
#: is possible on interlined work.
ROUTES_PER_GROUP_CAP = 5

#: One label query for a whole batch of findings — never one query per
#: finding: a single live VRH run raised 66,286 findings, and a per-finding
#: round trip would have made routing them take longer than the calculation.
#: The inner aggregate is bounded by the same id array as the outer filter,
#: so it reads only the stop_times rows of the trips actually asked about.
_SELECT_TRIP_LABELS_SQL = (
    "SELECT t.trip_id, t.block_id, t.route_id, r.short_name, r.long_name, "
    "d.first_departure_seconds, d.last_departure_seconds "
    "FROM canonical.trips AS t "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "LEFT JOIN ("
    "SELECT trip_id, min(departure_seconds) AS first_departure_seconds, "
    "max(departure_seconds) AS last_departure_seconds "
    "FROM canonical.stop_times "
    "WHERE trip_id = ANY(%s) AND departure_seconds IS NOT NULL "
    "GROUP BY trip_id"
    ") AS d ON d.trip_id = t.trip_id "
    "WHERE t.trip_id = ANY(%s) "
    "ORDER BY t.trip_id"
)


def _clock(seconds: int | None) -> str | None:
    """GTFS service-day seconds as a clock time a person reads.

    GTFS counts from "noon minus 12 hours" of the SERVICE day, so a trip
    that departs after midnight legitimately carries an hour of 24 or more
    (``25:10`` is 1:10 a.m. on the following calendar day). That convention
    is preserved rather than wrapped: wrapping would silently move a trip to
    the wrong day, and a dispatcher reading a service-day schedule already
    knows what ``25:10`` means. Returns None when the feed carries no
    departure time — absent renders as absent.
    """
    if seconds is None:
        return None
    total = int(seconds)
    if total < 0:
        # A negative schedule time is not representable as a clock time and
        # is never rendered as one; the raw value stays available upstream.
        return None
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"


def _fetch_trip_labels(conn, trip_ids: list[str]) -> dict[str, dict]:
    """One SELECT; returns {trip_id: label dict} for the trips that EXIST.

    A trip absent from the result is absent from the return value — the
    caller reports it as unmatched rather than inventing a row for it.
    """
    cur = conn.cursor()
    cur.execute(_SELECT_TRIP_LABELS_SQL, (trip_ids, trip_ids))
    labels: dict[str, dict] = {}
    for row in cur.fetchall():
        trip_id, block_id, route_id, short_name, long_name, first_s, last_s = row
        labels[str(trip_id)] = {
            "block_id": block_id,
            "route_id": route_id,
            "route_short_name": short_name,
            "route_long_name": long_name,
            "first_departure": _clock(first_s),
            "last_departure": _clock(last_s),
        }
    return labels


def _group_by_block(subject: SubjectRef, labels: dict[str, dict]) -> dict:
    """Build one finding's stored context: trips grouped by block.

    Determinism matters as much as readability — the same finding must
    produce the same context every run — so every ordering below is total:
    groups sort by first departure (the dispatcher's day runs forwards),
    then by block id, with unknowns last; ids inside a group keep the
    calculation's own order.

    When the subject names a VEHICLE (handoff 0032 — the gap-family
    findings are per-vehicle), the context carries it as
    ``{"vehicle": {"vehicle_id": ..., "label": ...}}``: the id always, the
    fleet label exactly as the feed broadcast it or null when it broadcast
    none — frozen here like every other label, never re-resolved, never
    invented. The key is ADDITIVE under CONTEXT_VERSION 1: a reader that
    predates it simply ignores it, and a context without it renders exactly
    as before.
    """
    ids = subject.ids
    buckets: dict[str | None, list[str]] = {}
    unmatched: list[str] = []
    seen: set[str] = set()
    for trip_id in ids:
        if trip_id in seen:
            continue
        seen.add(trip_id)
        label = labels.get(trip_id)
        if label is None:
            unmatched.append(trip_id)
            continue
        buckets.setdefault(label["block_id"], []).append(trip_id)

    groups: list[dict] = []
    for block_id, members in buckets.items():
        departures = [
            labels[t]["first_departure"]
            for t in members
            if labels[t]["first_departure"] is not None
        ]
        lasts = [
            labels[t]["last_departure"]
            for t in members
            if labels[t]["last_departure"] is not None
        ]
        routes: dict[str, dict] = {}
        for t in members:
            route_id = labels[t]["route_id"]
            if route_id is None or route_id in routes:
                continue
            routes[route_id] = {
                "route_id": route_id,
                "short_name": labels[t]["route_short_name"],
                "long_name": labels[t]["route_long_name"],
            }
        ordered_routes = sorted(
            routes.values(),
            key=lambda r: (r["short_name"] or "", r["route_id"]),
        )
        groups.append(
            {
                "block_id": block_id,
                "trip_count": len(members),
                "routes": ordered_routes[:ROUTES_PER_GROUP_CAP],
                "route_count": len(ordered_routes),
                # None when NO trip in the group carries a scheduled
                # departure — the span is unknown, and says so.
                "first_departure": min(departures) if departures else None,
                "last_departure": max(lasts) if lasts else None,
                "trip_ids": members[:TRIP_IDS_PER_GROUP_CAP],
            }
        )

    groups.sort(
        key=lambda g: (
            g["first_departure"] is None,
            g["first_departure"] or "",
            g["block_id"] is None,
            g["block_id"] or "",
        )
    )

    context = {
        "version": CONTEXT_VERSION,
        "kind": SUBJECT_TRIPS,
        "total": len(seen),
        "grouped_by": "block",
        "group_count": len(groups),
        "group_cap": GROUP_CAP,
        "trip_id_cap": TRIP_IDS_PER_GROUP_CAP,
        "groups": groups[:GROUP_CAP],
    }
    if subject.vehicle is not None:
        # The vehicle the finding concerns (handoff 0032): id always, the
        # feed's fleet label or null — the label travelled with the calc's
        # input rows, so nothing is looked up and nothing is invented.
        context["vehicle"] = {
            "vehicle_id": subject.vehicle.vehicle_id,
            "label": subject.vehicle.label,
        }
    if unmatched:
        # Trips Headway saw operating but that are not in the schedule feed
        # (an added/unscheduled trip, or a feed that changed under the
        # period). Reported as its own honest bucket — never folded into a
        # block it does not belong to.
        context["unmatched"] = {
            "trip_count": len(unmatched),
            "trip_ids": unmatched[:TRIP_IDS_PER_GROUP_CAP],
        }
    return context


#: kind -> resolver. The registry and types.SUBJECT_KINDS are asserted equal
#: by test: a kind without a resolver would produce a finding nobody can
#: label, which is the failure this whole mechanism exists to prevent.
_RESOLVERS = {SUBJECT_TRIPS: (_fetch_trip_labels, _group_by_block)}


def resolve_contexts(conn, findings: list[Finding]) -> list[dict | None]:
    """Resolve every finding's subject in ONE batch; returns one context (or
    None) per finding, in input order.

    None means the finding has no subject — a coverage ratio, a timezone
    declaration, a run-level summary. Those findings are about the run, not
    about identifiable rows, and they render exactly as they always have.

    Issues **no query at all** when no finding in the batch carries a
    subject, so every pre-0029 call site (and every unit test with a fake
    connection) behaves byte-for-byte as before.

    Fail-loudly: an unknown subject kind raises rather than quietly emitting
    an unlabelled finding, and any database error propagates unchanged.
    """
    wanted: dict[str, None] = {}
    for finding in findings:
        subject = finding.subject
        if subject is None:
            continue
        if subject.kind not in _RESOLVERS:
            raise ValueError(
                f"No resolver for subject kind {subject.kind!r} "
                f"(issue_type={finding.issue_type!r}). Known kinds: "
                f"{tuple(_RESOLVERS)}. A finding whose subject cannot be "
                f"resolved would reach a dispatcher as raw ids — the exact "
                f"failure the subject mechanism exists to prevent."
            )
        for trip_id in subject.ids:
            wanted.setdefault(trip_id, None)

    if all(f.subject is None for f in findings):
        return [None] * len(findings)

    # A subject with no trip ids (possible in principle for a pure vehicle
    # reference) still gets its context — it just needs no label query.
    labels = _fetch_trip_labels(conn, list(wanted)) if wanted else {}
    return [
        None if f.subject is None else _group_by_block(f.subject, labels)
        for f in findings
    ]


def resolver_kinds() -> tuple[str, ...]:
    """The kinds this module can resolve — compared against
    types.SUBJECT_KINDS by test so the two can never drift."""
    return tuple(sorted(_RESOLVERS))


__all__ = [
    "CONTEXT_VERSION",
    "GROUP_CAP",
    "ROUTES_PER_GROUP_CAP",
    "SUBJECT_KINDS",
    "TRIP_IDS_PER_GROUP_CAP",
    "resolve_contexts",
    "resolver_kinds",
]
