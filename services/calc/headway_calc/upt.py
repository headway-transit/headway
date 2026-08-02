"""upt_v0 — Unlinked Passenger Trips from TIDES passenger events (handoff 0005).

Regulatory basis (2026 NTD Policy Manual, Full Reporting — quotes verified
against docs/reference/ 2026-07-10; see REGULATORY_TRACKER.md):

- **UPT definition** (p. 143): "Unlinked Passenger Trips (UPT) are the number
  of boardings on public transportation vehicles during the fiscal year.
  Transit agencies must count passengers each time they board vehicles, no
  matter how many vehicles they use to travel from their origin to their
  destination. If a transit vehicle changes routes while passengers are
  onboard (interlining), transit agencies should not recount the passengers.
  Employees or contractors on transit agency business are not passengers."
- **Missing-trip rule** (p. 146): "If these vehicle trips are 2 percent or
  less of the total, transit agencies should factor up the data to account
  for the missing trips. However, if the vehicle trips with missing data
  exceed 2 percent of total trips, agencies must have a qualified
  statistician approve the factoring method used to account for the missing
  percentage." The 0.02 default here is therefore a REAL FTA threshold, not
  an engineering placeholder.
- **APC validation examples** (p. 151): "agencies may flag trips or blocks
  where the difference between boardings and alightings is greater than 10
  percent, or trips where the passenger load drops below zero."

Event vocabulary — verified TIDES enum (do NOT guess; handoff 0005 open
question resolved): the ``event_type`` values below were verified 2026-07-10
against the live TIDES spec,
https://github.com/TIDES-transit/TIDES ``spec/passenger_events.schema.json``
(main branch, repo HEAD 7ddaa7ab820eeca1cc7a681ba9ae79a72ba10af1; the schema
file's last change is commit d887d42ce081f3fb6155664a3c486101d62ec52b,
2023-12-11). The enum's passenger values are exactly ``"Passenger boarded"``
and ``"Passenger alighted"``; bike events ("Individual bike boarded"/
"... alighted") are NOT passengers under the p. 143 definition and are never
counted.

v0 scope (documented approximations, mirroring vrm_v0/vrh_v0):

- Trip assignment (``trip_id`` not None, from TIDES ``trip_id_performed``) is
  the revenue-service proxy: unassigned events are excluded from the counted
  figure (consistent with the position-derived calcs; no deadhead handling).
- The missing-trip factor-up is FLEET-WIDE, not per mode/type-of-service —
  the manual speaks of totals per mode/TOS; mode-awareness is a documented
  limitation (handoff 0005 open question, owner NTD role).
- APC certification (manual pp. 147-148) is an agency workflow, not calc
  logic; simulated-source data can never yield a certifiable figure and is
  flagged per the handoff-0005 simulated-data rule.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input events.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable, Mapping

from headway_calc.attestation import (
    P146_ATTESTATION_BASIS,
    AttestationContext,
    governing_attestation,
)
from headway_calc._vocabulary import short_id
from headway_calc.revenue_window import (
    INSIDE_WINDOW,
    NO_WINDOW,
    OUTSIDE_WINDOW,
    RevenueWindow,
)
from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SUBJECT_TRIPS,
    BoardingReviewItem,
    CalcResult,
    Finding,
    HumanBoardingVerdict,
    PassengerEvent,
    SubjectRef,
    UptDetail,
)

CALC_NAME = "upt_v0"
#: 0.3.0 (handoff 0040): revenue classification of no-run boardings. A
#: passenger event may carry an assignment status
#: (canonical.passenger_events.revenue_classification, migration 0039):
#: 'unassigned' — a no-run "ghost" boarding a vehicle fired while moving with
#: the APC on but not logged into a run — is a vehicle NOT in revenue service
#: (2026 NTD Policy Manual p. 128), so it is NOT an unlinked passenger trip.
#: 0.3.0 EXCLUDES the auto-classified non-revenue ones from UPT and HOLDS the
#: ambiguous mid-service ones OUT of the figure pending human review (the
#: exclude-until-classified default), reporting the split
#: (revenue / excluded-non-revenue / pending-review) in the detail. A feed
#: that never sets revenue_classification (every first-party TIDES feed, every
#: pre-0040 row) computes BYTE-FOR-BYTE as 0.2.0: the trip-assignment proxy is
#: unchanged (trip_id present = revenue counted; trip_id NULL = excluded), no
#: split keys appear unless a classified event exists, and the missing-trip
#: factor is untouched. 0.2.0 is RETAINED runnable as compute_upt_v0_2_0 and
#: 0.1.0 as compute_upt_v0_1_0 (the sscls convention — shipped versions stay
#: reproducible).
#:
#: 0.4.0 (handoff 0040, the review sub-wave) CLOSES THE LOOP. 0.3.0 could hold
#: an ambiguous boarding pending forever, because nothing could ever answer
#: it: there was no way for a human to say what it was. Now there is
#: (dq.boarding_revenue_reviews), and 0.4.0 reads those answers back. A no-run
#: boarding a named person classified 'revenue' is COUNTED; one classified
#: 'non_revenue' is EXCLUDED; anything still undecided is held exactly as
#: 0.3.0 held it. Each decision's justification note, author and timestamp are
#: copied verbatim into the detail, so the figure carries the reasoning that
#: defends it. A run with no recorded decisions computes BYTE-FOR-BYTE as
#: 0.3.0, which is retained runnable as compute_upt_v0_3_0.
CALC_VERSION = "0.4.0"

#: The transform's assignment status (migration 0039). 'unassigned' is the
#: no-run ghost boarding; 'assigned' resolved to a run; None (the pre-0040
#: default) means no status was recorded and the trip-assignment proxy governs.
UNASSIGNED = "unassigned"

#: The revenue VERDICT upt_v0 derives for a no-run boarding (the calc owns the
#: number, not the transform). Recorded in the detail split and the finding.
VERDICT_REVENUE = "revenue"
VERDICT_EXCLUDED_NON_REVENUE = "excluded_non_revenue"
VERDICT_PENDING_REVIEW = "pending_review"
#: 'boardings' would be ambiguous against the counted base; the persisted unit
#: names the NTD measure itself.
UNIT = "unlinked_passenger_trips"

#: Verified TIDES event_type enum values (see module docstring for the
#: citation — verified 2026-07-10, never from memory).
BOARDING_EVENT_TYPE = "Passenger boarded"
ALIGHTING_EVENT_TYPE = "Passenger alighted"

#: p. 146 missing-trip threshold: "2 percent or less of the total" may be
#: factored up; above it "agencies must have a qualified statistician approve
#: the factoring method". A REAL FTA threshold (2026 NTD Policy Manual),
#: explicit input, recorded in the run's provenance.
MISSING_TRIP_THRESHOLD: Decimal = Decimal("0.02")

#: p. 151 APC validation example: "difference between boardings and
#: alightings is greater than 10 percent". Explicit input, recorded in the
#: run's provenance.
IMBALANCE_THRESHOLD: Decimal = Decimal("0.10")

#: Quantum for the REPORTED missing share (0.0001, ROUND_HALF_EVEN — the same
#: engineering convention as the coverage ratios; the threshold COMPARISON is
#: exact, never the quantized value).
_SHARE_QUANTUM = Decimal("0.0001")

#: Quantum for the REPORTED factor (provenance only; the reported UPT value
#: is computed from the exact fraction, then quantized to whole boardings).
_FACTOR_QUANTUM = Decimal("0.000001")

#: The reported UPT quantum: whole boardings (Decimal 1, ROUND_HALF_EVEN). A
#: boarding count is integral by nature; the factor-up may produce a
#: fraction, which is rounded half-even to the nearest whole boarding — a
#: documented engineering rounding convention (the p. 146 factoring method
#: itself prescribes no rounding rule).
_UPT_QUANTUM = Decimal("1")

#: The envelope source of REAL TIDES feeds; anything else (e.g.
#: "tides_simulated") triggers the simulated-source info finding.
_REAL_SOURCE = "tides"

#: Quantum for a share rendered as a percentage in finding prose (handoff
#: 0029). The percentage is a RESTATEMENT of the already-quantized
#: missing_share, never a second computation of it: 0.8076 -> "80.76%".
_PERCENT_QUANTUM = Decimal("0.01")


def _as_percent(share: Decimal) -> str:
    """The reported share, said the way a person reads it.

    'missing share 0.8076' is precise and unreadable; '80.76%' is the same
    number in the vocabulary of the person who has to act on it. Both appear
    in the finding — the decimal for provenance, the percentage for the
    human — and the percentage is derived from the quantized reported share,
    so the two can never disagree.
    """
    return f"{(share * 100).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_EVEN)}%"


def _sorted_events(events: Iterable[PassengerEvent]) -> list[PassengerEvent]:
    """Canonical total order (matches the reader's ORDER BY): input order is
    irrelevant to the result."""
    return sorted(
        events,
        key=lambda e: (e.event_timestamp, e.passenger_event_id, e.source_record_id),
    )


def _stop_order_key(event: PassengerEvent) -> tuple:
    """p. 151 running-load order: trip_stop_sequence, then event_timestamp.

    A NULL trip_stop_sequence (nullable in canonical.passenger_events) sorts
    AFTER all numbered stops — a documented deterministic convention;
    passenger_event_id breaks remaining ties.
    """
    return (
        event.trip_stop_sequence is None,
        event.trip_stop_sequence if event.trip_stop_sequence is not None else 0,
        event.event_timestamp,
        event.passenger_event_id,
    )


def _null_count_warning(event: PassengerEvent) -> Finding:
    role = "boarding" if event.event_type == BOARDING_EVENT_TYPE else "alighting"
    return Finding(
        issue_type="apc_null_count",
        severity=SEVERITY_WARNING,
        # Ids in the title are shortened for scanning (handoff 0032);
        # the full identifiers stay in the description below.
        title=(
            f"NULL event_count on {role} event "
            f"{short_id(event.passenger_event_id)} "
            f"(trip {short_id(event.trip_id) if event.trip_id else 'unassigned'})"
        ),
        description=(
            f"Passenger event {event.passenger_event_id!r} (trip_id="
            f"{event.trip_id!r}, vehicle_id={event.vehicle_id!r}, "
            f"event_type={event.event_type!r}, "
            f"{event.event_timestamp.isoformat()}) carries a NULL event_count. "
            f"The TIDES schema documents a default of 1, but the handoff-0005 "
            f"contract preserves NULL as NULL — the calculation NEVER coalesces "
            f"a missing count to a guessed number: this event contributed 0 to "
            f"the {'counted UPT figure' if role == 'boarding' else 'p. 151 validation arithmetic'} "
            f"and is cited here instead of appearing in lineage."
        ),
        source_record_ids=(event.source_record_id,),
        # The trip is what an APC technician goes and looks at (handoff
        # 0029); trip_id is never None here — unassigned events return
        # before this warning is built.
        subject=SubjectRef(kind=SUBJECT_TRIPS, ids=(event.trip_id,)),
    )


def _no_run_warning(event: PassengerEvent, verdict: str, reason: str) -> Finding:
    """ONE warning per no-run boarding — excluded or held pending (handoff
    0040). No trip subject (a no-run boarding has, by definition, no trip);
    the raw record is cited so the later human-in-the-loop wave can find it.
    """
    excluded = verdict == VERDICT_EXCLUDED_NON_REVENUE
    return Finding(
        issue_type=(
            "boarding_excluded_non_revenue"
            if excluded
            else "boarding_pending_revenue_review"
        ),
        severity=SEVERITY_WARNING,
        title=(
            f"No-run boarding {short_id(event.passenger_event_id)} "
            + (
                "excluded as non-revenue (prep / pull-in)"
                if excluded
                else "held pending revenue review"
            )
            + f" — vehicle {short_id(event.vehicle_id)}, "
            f"{event.event_timestamp.isoformat()}"
        ),
        description=(
            f"Passenger event {event.passenger_event_id!r} (vehicle_id="
            f"{event.vehicle_id!r}, {event.event_timestamp.isoformat()}, "
            f"count={event.event_count}) carried NO run assignment "
            "(revenue_classification 'unassigned'): "
            + reason
            + ". "
            + (
                "It is EXCLUDED from Unlinked Passenger Trips (a vehicle not "
                "in revenue service is not carrying passengers) and recorded "
                "in the metric detail's revenue split — never dropped, never "
                "silently counted."
                if excluded
                else "It is HELD OUT of the reported figure until a human "
                "classifies it revenue or non-revenue (the exclude-until-"
                "classified default), so a boarding of unknown revenue status "
                "cannot silently inflate or deflate a certified number. It is "
                "recorded in the metric detail's revenue split and routed to "
                "the revenue review queue, where a data steward classifies "
                "it and writes down why. The figure changes only when the "
                "calculation is re-run after that decision."
            )
        ),
        source_record_ids=(event.source_record_id,),
    )


def _human_verdict_info(
    event: PassengerEvent, decision: HumanBoardingVerdict
) -> Finding:
    """ONE info finding per human-classified no-run boarding (handoff 0040,
    review sub-wave).

    INFO, not warning: nothing here is unresolved. A person with a name looked
    at this boarding, decided what it was, and wrote down why — which is the
    outcome the pending warning was asking for. The finding exists so the
    decision is visible in the data-quality trail beside the boardings still
    waiting, and so the reason travels with the evidence rather than only with
    the figure.

    The justification is quoted VERBATIM. The calculation never summarises,
    paraphrases or grades a human's reasoning; it carries it.
    """
    counted = decision.verdict == "revenue"
    return Finding(
        issue_type="boarding_classified_by_review",
        severity=SEVERITY_INFO,
        title=(
            f"No-run boarding {short_id(event.passenger_event_id)} classified "
            + ("REVENUE" if counted else "NON-REVENUE")
            + f" by {decision.classified_by} — vehicle "
            f"{short_id(event.vehicle_id)}, "
            f"{event.event_timestamp.isoformat()}"
        ),
        description=(
            f"Passenger event {event.passenger_event_id!r} (vehicle_id="
            f"{event.vehicle_id!r}, {event.event_timestamp.isoformat()}, "
            f"count={event.event_count}) carried no run assignment and was "
            f"held pending review. "
            f"{decision.classified_by} classified it "
            + (
                "REVENUE on "
                if counted
                else "NON-REVENUE on "
            )
            + f"{decision.classified_at.isoformat()}, with this "
            f"justification: “{decision.justification}” "
            + (
                "Its boardings are COUNTED in Unlinked Passenger Trips on "
                "this run."
                if counted
                else "Its boardings are EXCLUDED from Unlinked Passenger "
                "Trips on this run (a vehicle not in revenue service is not "
                "carrying passengers, 2026 NTD Policy Manual p. 128)."
            )
            + " The decision, its author and its reason are recorded in the "
            "metric detail so the correction can be defended rather than "
            "asserted."
        ),
        source_record_ids=(event.source_record_id,),
    )


def _review_item(event: PassengerEvent, reason: str) -> BoardingReviewItem:
    """The structured hand-off of ONE undecided boarding to a person.

    Everything a reviewer needs to decide, and nothing the calculation had to
    invent to produce it: the boarding's own identity and time, the vehicle
    the feed named, how many boardings are at stake, and the calculation's own
    words for why it refused to guess.
    """
    return BoardingReviewItem(
        passenger_event_id=event.passenger_event_id,
        source_record_id=event.source_record_id,
        service_date=event.service_date,
        event_timestamp=event.event_timestamp,
        vehicle_id=event.vehicle_id,
        event_count=event.event_count,
        suggested_verdict=VERDICT_PENDING_REVIEW,
        suggested_reason=reason,
    )


def _classify_no_run(
    event: PassengerEvent,
    revenue_windows: Mapping[date, RevenueWindow],
) -> tuple[str, str]:
    """Auto-classify one no-run ('unassigned') boarding — (verdict, reason).

    The revenue verdict is the CALC's, derived from the transform's
    assignment status (the row already resolved to no run) corroborated by
    the schedule-derived revenue window (handoff 0040 design points 3–4):

    - OUTSIDE the day's revenue window (before the first scheduled departure
      or after the last scheduled arrival) — prep / pull-out / pull-in, a
      vehicle not in revenue service (p. 128): suggested NON-REVENUE, excluded
      from UPT with the reason recorded;
    - INSIDE the window (mid-service) — genuinely ambiguous: it fits neither
      prep nor detour and could be a real catch-up bus dispatched without a
      formal trip assignment (design point 7). Held PENDING human review — the
      conservative exclude-until-classified default — never silently counted
      and never silently excluded;
    - NO window derivable for the date (no schedule, no agency timezone) —
      the corroborating signal is absent, so the boarding is held PENDING
      review rather than guessed either way.
    """
    window = revenue_windows.get(event.service_date)
    placement = NO_WINDOW if window is None else window.classify(event.event_timestamp)
    if placement == OUTSIDE_WINDOW:
        return (
            VERDICT_EXCLUDED_NON_REVENUE,
            "no run assignment and outside the day's revenue-service window "
            "(before the first scheduled departure or after the last "
            "scheduled arrival) — prep / pull-out / pull-in, a vehicle not in "
            "revenue service (2026 NTD Policy Manual p. 128)",
        )
    if placement == INSIDE_WINDOW:
        return (
            VERDICT_PENDING_REVIEW,
            "no run assignment but WITHIN the day's revenue-service window — "
            "ambiguous (could be a catch-up bus dispatched without a formal "
            "trip assignment); held pending human review, never counted or "
            "excluded silently",
        )
    return (
        VERDICT_PENDING_REVIEW,
        "no run assignment and no revenue-service window could be derived for "
        "this service date (no schedule or no agency timezone) — held pending "
        "human review rather than guessed",
    )


def compute_upt(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations: Iterable[AttestationContext] = (),
    revenue_windows: Mapping[date, RevenueWindow] | None = None,
    boarding_reviews: Mapping[str, HumanBoardingVerdict] | None = None,
) -> CalcResult:
    """Compute upt_v0 (version 0.4.0) — Unlinked Passenger Trips.

    Human classifications (0.4.0, handoff 0040 review sub-wave).
    ``boarding_reviews`` maps ``passenger_event_id`` to the decision a named
    person recorded in the revenue review queue. A held no-run boarding with a
    recorded decision is no longer held: 'revenue' COUNTS it, 'non_revenue'
    EXCLUDES it, and either way the person, the timestamp and the
    justification note travel verbatim into the detail and into one info
    finding — the receipt that makes the correction defensible instead of
    asserted. A human-counted boarding is added to the figure AFTER the
    p. 146 missing-trip factor-up and never inside it: the factor exists to
    account for trips whose data is missing, and a no-run boarding is not a
    trip, so multiplying a human-confirmed count by it would invent riders
    nobody observed. Boardings still undecided are held exactly as 0.3.0 held
    them, and are emitted as ``review_items`` for the queue. With no recorded
    decisions the result is byte-for-byte 0.3.0's.

    Revenue classification of no-run boardings (handoff 0040, design points
    3–5). An event whose ``revenue_classification`` (migration 0039) is
    ``'unassigned'`` is a no-run "ghost" boarding — a vehicle fired the APC
    while moving with no run assignment at all (prep / pull-out / pull-in, or
    rarely a catch-up bus dispatched without a trip). A vehicle not logged
    into a run is NOT in revenue service (p. 128), so such a boarding is NOT
    an unlinked passenger trip. Each is auto-classified against the
    schedule-derived revenue window (``revenue_windows``, keyed by service
    date — a CORROBORATING signal; the primary discriminator is the no-run
    assignment itself):

    - outside the window → suggested NON-REVENUE, EXCLUDED from UPT, reason
      recorded;
    - inside the window (or no window derivable) → PENDING human review, held
      OUT of the figure (the conservative exclude-until-classified default).

    Every no-run boarding is COUNTED INTO THE SPLIT (revenue / excluded-non-
    revenue / pending-review) in the detail and cited by ONE warning — never
    dropped and never silently counted. The double-count guard is structural:
    a no-run boarding has ``trip_id`` None, so it contributes to neither the
    counted UPT base nor the operated/missing-trip denominators — the p. 146
    missing-trip factor is untouched (an excluded boarding can never inflate
    or deflate it). A feed that sets no ``revenue_classification`` computes
    BYTE-FOR-BYTE as 0.2.0.

    Base count (p. 143: "the number of boardings on public transportation
    vehicles"): the sum of ``event_count`` over events whose ``event_type``
    is the verified TIDES boarding value (``"Passenger boarded"``) AND whose
    ``trip_id`` is not None — trip assignment is the v0 revenue-service
    proxy, consistent with vrm_v0/vrh_v0 (documented approximation). An
    event with ``event_count`` None contributes 0 and one warning finding
    ``'apc_null_count'`` citing the record — never a silently guessed number
    (NULL-count boarding/alighting events are cited by their warnings, not
    by lineage).

    Validations (p. 151, quoted verbatim: "agencies may flag trips or blocks
    where the difference between boardings and alightings is greater than 10
    percent, or trips where the passenger load drops below zero"):

    - per trip, |boardings - alightings| > ``imbalance_threshold`` x
      boardings -> one warning ``'apc_count_imbalance'`` citing the trip's
      boarding/alighting records (exact comparison, no quantized ratio);
    - per trip, the running load (events ordered by trip_stop_sequence then
      event_timestamp; boardings add, alightings subtract) dropping below
      zero -> one warning ``'apc_negative_load'`` citing the record at which
      the load first went negative.

    Missing-trip rule (p. 146, quoted verbatim: "If these vehicle trips are 2
    percent or less of the total, transit agencies should factor up the data
    to account for the missing trips. However, if the vehicle trips with
    missing data exceed 2 percent of total trips, agencies must have a
    qualified statistician approve the factoring method used to account for
    the missing percentage."): operated trips with ZERO passenger events are
    missing; share = missing/operated (exact comparison against
    ``missing_trip_threshold``, default 0.02 — a REAL FTA threshold).

    - share <= threshold: the value is factored up DETERMINISTICALLY per the
      FTA-sanctioned method — UPT_reported = counted x operated/(operated -
      missing), computed from the exact fraction and quantized to whole
      boardings (Decimal 1, ROUND_HALF_EVEN — documented engineering
      rounding; the manual prescribes none). The factor and all inputs are
      recorded in the detail.
    - share > threshold WITHOUT an applicable attestation: ONE blocking
      finding ``'apc_missing_trips_above_fta_threshold'`` and value None —
      the statistician-approved factoring is a human workflow, never
      guessed. Byte-for-byte the 0.1.0 refusal (regression-pinned).
    - share > threshold WITH an applicable attestation (handoff 0019 —
      ``attestations`` are AttestationContexts already matched to this
      run's scope and period by the caller via
      headway_calc.attestation.applicable_attestations; the calc re-checks
      metric — a non-'upt' attestation raises ValueError — and skips
      revoked ones; the earliest-entered survivor governs): the SAME
      deterministic factor-up as the ≤2% branch — the p. 146 sentence
      permits it once "a qualified statistician approve[s] the factoring
      method" — plus ONE info finding
      ``'apc_missing_trips_attested_factor_up'`` naming the attestation and
      quoting p. 146, and the attestation's full provenance dict in
      ``detail.attestation`` (the figure carries it permanently).
      Attestations NEVER touch anything else: the ≤2% branch ignores them
      entirely (byte-identical output), simulated-source flags stand, and
      no other finding changes.
    - zero operated trips (degenerate period): nothing operated, nothing
      missing — share 0, factor 1, the counted figure stands.

    Simulated sources (handoff 0005 binding rule): any event whose
    ``source`` != "tides" yields ONE info finding ``'simulated_source_data'``
    listing the sources; ``source_mix`` (event counts per source) is ALWAYS
    in the detail.

    ``input_record_ids`` are the distinct source_record_ids of counted
    boarding events (lineage); NULL-count events' records are cited by their
    ``apc_null_count`` warnings instead. Returns a CalcResult whose detail is
    an UptDetail (present on blocked results too — the evidence always
    travels).
    """
    missing_trip_threshold = Decimal(str(missing_trip_threshold))
    imbalance_threshold = Decimal(str(imbalance_threshold))
    revenue_windows = revenue_windows or {}
    ordered = _sorted_events(events)
    operated = sorted(set(operated_trip_ids))

    warnings: list[Finding] = []
    infos: list[Finding] = []

    # --- revenue classification of no-run boardings (handoff 0040) -----------
    # A boarding marked 'unassigned' (migration 0039) is a no-run ghost the
    # vehicle fired while not logged into a run — NOT in revenue service
    # (p. 128), so NOT a UPT. Auto-classify each against the schedule-derived
    # revenue window: outside → excluded non-revenue; inside/no-window →
    # pending human review (exclude-until-classified default). These
    # boardings are COUNTED INTO THE SPLIT and cited by ONE warning — never
    # dropped, never silently counted. Their trip_id is None, so they touch
    # neither the counted base nor the missing-trip denominators below (the
    # double-count guard is structural, not a subtraction).
    #
    # 0.4.0: before the window is consulted at all, a boarding a NAMED PERSON
    # already decided in the revenue review queue takes their answer — the
    # human is the higher authority here by construction, because the only
    # boardings that reach the queue are the ones the schedule could not
    # settle. Their note travels into the figure's detail verbatim.
    excluded_non_revenue_boardings = 0
    pending_review_boardings = 0
    human_revenue_boardings = 0
    human_non_revenue_boardings = 0
    human_classifications: list[dict] = []
    review_items: list[BoardingReviewItem] = []
    excluded_record_ids: dict[str, None] = {}
    pending_record_ids: dict[str, None] = {}
    reviews = boarding_reviews or {}

    # --- base count (p. 143) + lineage + null-count warnings ----------------
    counted_boardings = 0
    input_ids: dict[str, None] = {}
    source_mix: dict[str, int] = {}
    trips_with_any_event: set[str] = set()
    null_count_warnings: list[Finding] = []
    for event in ordered:
        source_mix[event.source] = source_mix.get(event.source, 0) + 1
        if event.trip_id is not None:
            trips_with_any_event.add(event.trip_id)
        if event.trip_id is None:
            # No-run boarding: classify it into the revenue split rather than
            # simply skipping it (the pre-0040 trip-assignment proxy). Only
            # BOARDING events with an explicit 'unassigned' status and a
            # non-NULL count carry a boarding to classify; a NULL count is
            # warned exactly as an assigned NULL count would be.
            if (
                event.revenue_classification == UNASSIGNED
                and event.event_type == BOARDING_EVENT_TYPE
            ):
                if event.event_count is None:
                    null_count_warnings.append(_null_count_warning(event))
                else:
                    verdict, reason = _classify_no_run(event, revenue_windows)
                    decision = (
                        reviews.get(event.passenger_event_id)
                        if verdict == VERDICT_PENDING_REVIEW
                        else None
                    )
                    if decision is not None:
                        # A person answered this one. Their words, their name,
                        # their timestamp — carried, never paraphrased.
                        human_classifications.append(
                            {
                                "passenger_event_id": event.passenger_event_id,
                                "source_record_id": event.source_record_id,
                                "service_date": event.service_date.isoformat(),
                                "event_timestamp": (
                                    event.event_timestamp.isoformat()
                                ),
                                "vehicle_id": event.vehicle_id,
                                "event_count": event.event_count,
                                "verdict": decision.verdict,
                                "justification": decision.justification,
                                "classified_by": decision.classified_by,
                                "classified_at": (
                                    decision.classified_at.isoformat()
                                ),
                            }
                        )
                        if decision.verdict == "revenue":
                            human_revenue_boardings += event.event_count
                            # It IS in the figure, so its raw record IS
                            # lineage — the walk from the number back to the
                            # bytes must include the boardings a human added.
                            input_ids.setdefault(event.source_record_id, None)
                        else:
                            human_non_revenue_boardings += event.event_count
                            excluded_record_ids.setdefault(
                                event.source_record_id, None
                            )
                        infos.append(_human_verdict_info(event, decision))
                    elif verdict == VERDICT_EXCLUDED_NON_REVENUE:
                        excluded_non_revenue_boardings += event.event_count
                        excluded_record_ids.setdefault(event.source_record_id, None)
                        warnings.append(_no_run_warning(event, verdict, reason))
                    else:  # VERDICT_PENDING_REVIEW, still undecided
                        pending_review_boardings += event.event_count
                        pending_record_ids.setdefault(event.source_record_id, None)
                        review_items.append(_review_item(event, reason))
                        warnings.append(_no_run_warning(event, verdict, reason))
            continue  # revenue-service proxy: unassigned events not counted
        if event.event_type == BOARDING_EVENT_TYPE:
            if event.event_count is None:
                null_count_warnings.append(_null_count_warning(event))
            else:
                counted_boardings += event.event_count
                input_ids.setdefault(event.source_record_id, None)
        elif event.event_type == ALIGHTING_EVENT_TYPE:
            # Alighting counts feed the p. 151 validations below; a NULL
            # there is treated as 0 in the same never-guess spirit and is
            # warned identically.
            if event.event_count is None:
                null_count_warnings.append(_null_count_warning(event))

    # --- p. 151 validations, per trip ---------------------------------------
    by_trip: dict[str, list[PassengerEvent]] = {}
    for event in ordered:
        if event.trip_id is None:
            continue
        if event.event_type in (BOARDING_EVENT_TYPE, ALIGHTING_EVENT_TYPE):
            by_trip.setdefault(event.trip_id, []).append(event)

    imbalance_warnings: list[Finding] = []
    negative_load_warnings: list[Finding] = []
    for trip_id in sorted(by_trip):
        trip_events = by_trip[trip_id]
        boardings = sum(
            e.event_count or 0
            for e in trip_events
            if e.event_type == BOARDING_EVENT_TYPE
        )
        alightings = sum(
            e.event_count or 0
            for e in trip_events
            if e.event_type == ALIGHTING_EVENT_TYPE
        )
        trip_record_ids: dict[str, None] = {}
        for e in trip_events:
            trip_record_ids.setdefault(e.source_record_id, None)

        # "difference between boardings and alightings is greater than 10
        # percent" (of boardings) — exact integer/Decimal comparison.
        if Decimal(abs(boardings - alightings)) > imbalance_threshold * Decimal(
            boardings
        ):
            imbalance_warnings.append(
                Finding(
                    issue_type="apc_count_imbalance",
                    severity=SEVERITY_WARNING,
                    # Shortened id in the title (handoff 0032); the
                    # full id stays in the description and the subject.
                    title=(
                        f"Boarding/alighting imbalance on trip "
                        f"{short_id(trip_id)}: "
                        f"{boardings} boarded vs {alightings} alighted"
                    ),
                    description=(
                        f"Trip {trip_id!r} counted {boardings} boardings and "
                        f"{alightings} alightings: |{boardings} - {alightings}| = "
                        f"{abs(boardings - alightings)} exceeds "
                        f"{imbalance_threshold} x boardings. Flagged per the 2026 "
                        f"NTD Policy Manual p. 151 APC validation example "
                        f"('agencies may flag trips or blocks where the "
                        f"difference between boardings and alightings is greater "
                        f"than 10 percent'). The figure stands; the trip's counts "
                        f"are suspect and should be reviewed in the agency's APC "
                        f"validation workflow."
                    ),
                    source_record_ids=tuple(trip_record_ids),
                    subject=SubjectRef(kind=SUBJECT_TRIPS, ids=(trip_id,)),
                )
            )

        # "trips where the passenger load drops below zero" — running load in
        # stop-sequence order (then event time; NULL sequence sorts last).
        load = 0
        for e in sorted(trip_events, key=_stop_order_key):
            if e.event_type == BOARDING_EVENT_TYPE:
                load += e.event_count or 0
            else:
                load -= e.event_count or 0
            if load < 0:
                negative_load_warnings.append(
                    Finding(
                        issue_type="apc_negative_load",
                        severity=SEVERITY_WARNING,
                        # Shortened id in the title (handoff 0032);
                        # the full id stays in the description/subject.
                        title=(
                            f"Passenger load drops below zero on trip "
                            f"{short_id(trip_id)} (load {load})"
                        ),
                        description=(
                            f"Running the boarding/alighting events of trip "
                            f"{trip_id!r} in stop-sequence order, the passenger "
                            f"load first drops below zero at event "
                            f"{e.passenger_event_id!r} (trip_stop_sequence="
                            f"{e.trip_stop_sequence!r}, "
                            f"{e.event_timestamp.isoformat()}): load {load}. "
                            f"Flagged per the 2026 NTD Policy Manual p. 151 APC "
                            f"validation example ('trips where the passenger "
                            f"load drops below zero'). The figure stands; the "
                            f"trip's counts are suspect and should be reviewed."
                        ),
                        source_record_ids=(e.source_record_id,),
                        subject=SubjectRef(kind=SUBJECT_TRIPS, ids=(trip_id,)),
                    )
                )
                break  # one finding per trip: the first drop is the evidence

    warnings.extend(null_count_warnings)
    warnings.extend(imbalance_warnings)
    warnings.extend(negative_load_warnings)

    # --- simulated-source rule (handoff 0005) --------------------------------
    simulated_sources = sorted(s for s in source_mix if s != _REAL_SOURCE)
    if simulated_sources:
        simulated_record_ids: dict[str, None] = {}
        for event in ordered:
            if event.source != _REAL_SOURCE:
                simulated_record_ids.setdefault(event.source_record_id, None)
        infos.append(
            Finding(
                issue_type="simulated_source_data",
                severity=SEVERITY_INFO,
                title=(
                    f"Passenger events include non-'tides' source(s): "
                    f"{', '.join(simulated_sources)}"
                ),
                description=(
                    f"{sum(source_mix[s] for s in simulated_sources)} of "
                    f"{len(ordered)} passenger events carry a source other than "
                    f"'tides': "
                    + ", ".join(f"{s} ({source_mix[s]} events)" for s in simulated_sources)
                    + ". Per the handoff-0005 simulated-data rule, simulator "
                    "output is permanently distinguishable in provenance and a "
                    "certifiable figure containing simulated records is a "
                    "contradiction the DQ trail must make visible: this figure "
                    "is NOT certifiable or reportable. The full source mix is "
                    "recorded in the metric value's detail."
                ),
                source_record_ids=tuple(simulated_record_ids),
            )
        )

    # --- pending-review summary (handoff 0040) -------------------------------
    # When any no-run boarding is held pending human review, ONE info finding
    # states the count and the exclude-until-classified default so the
    # certification layer (Backend) knows the reported figure holds these OUT
    # until classified — a boarding of unknown revenue status never silently
    # inflates or deflates a certified number. The per-boarding warnings above
    # carry the individual records; this is the roll-up.
    if pending_review_boardings:
        infos.append(
            Finding(
                issue_type="boardings_pending_revenue_review",
                severity=SEVERITY_INFO,
                title=(
                    f"{pending_review_boardings} boarding(s) held pending "
                    "revenue review — excluded until classified"
                ),
                description=(
                    f"{pending_review_boardings} no-run boarding(s) across "
                    f"{len(pending_record_ids)} record(s) fell WITHIN the "
                    "day's revenue-service window (or no window was derivable) "
                    "and are genuinely ambiguous — they could be non-revenue "
                    "prep or a real catch-up bus dispatched without a formal "
                    "trip assignment (2026 NTD Policy Manual p. 128 / handoff "
                    "0040). They are HELD OUT of the reported figure under the "
                    "exclude-until-classified default until a data steward "
                    "classifies them in the revenue review queue and writes "
                    "down why, so a certified "
                    "Unlinked Passenger Trips figure never counts a boarding of "
                    "unknown revenue status. Classifying them does not change "
                    "this figure: it changes what the NEXT run computes. The "
                    "split is in the metric "
                    "detail's revenue_classification block; each boarding's "
                    "record is cited by its own 'boarding_pending_revenue_"
                    "review' warning."
                ),
                source_record_ids=tuple(pending_record_ids),
            )
        )

    # --- missing-trip rule (p. 146) ------------------------------------------
    operated_count = len(operated)
    missing = [t for t in operated if t not in trips_with_any_event]
    missing_count = len(missing)
    trips_with_events_count = operated_count - missing_count
    exact_share = (
        Decimal(0)
        if operated_count == 0
        else Decimal(missing_count) / Decimal(operated_count)
    )
    missing_share = exact_share.quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_EVEN)

    # Exact threshold line: missing/operated > threshold <=>
    # missing > threshold * operated (never the quantized share).
    above_threshold = Decimal(missing_count) > missing_trip_threshold * Decimal(
        operated_count
    )

    blocking_issues: tuple[Finding, ...] = ()
    factor_applied: Decimal | None = None
    value: Decimal | None = None
    attestation_provenance: dict | None = None
    governing = governing_attestation(attestations, "upt")
    if above_threshold and governing is not None:
        # The p. 146 sentence's OWN permission path (handoff 0019): a
        # qualified statistician approved the factoring method, recorded as
        # an unrevoked in-scope cert.attestations row — so the SAME
        # deterministic factor-up as the ≤2% branch applies, and the figure
        # carries the attestation's provenance permanently. missing_count>0
        # here by construction (share > threshold > 0).
        exact_factor = Decimal(operated_count) / Decimal(
            operated_count - missing_count
        )
        value = (
            Decimal(counted_boardings)
            * Decimal(operated_count)
            / Decimal(operated_count - missing_count)
        ).quantize(_UPT_QUANTUM, rounding=ROUND_HALF_EVEN)
        factor_applied = exact_factor.quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        attestation_provenance = governing.to_provenance_dict()
        infos.append(
            Finding(
                issue_type="apc_missing_trips_attested_factor_up",
                severity=SEVERITY_INFO,
                title=(
                    f"Factored beyond the 2% threshold under a "
                    f"statistician-approved method — attestation "
                    f"#{governing.attestation_id}"
                ),
                description=(
                    f"{missing_count} of {operated_count} operated trips "
                    f"(observed in canonical.vehicle_positions) have zero "
                    f"passenger events: missing share {missing_share} exceeds "
                    f"the threshold of {missing_trip_threshold}. The 2026 NTD "
                    f"Policy Manual p. 146 permits factoring here only with "
                    f"approval: '{P146_ATTESTATION_BASIS}' That approval is "
                    f"on record as attestation #{governing.attestation_id} — "
                    f"statistician {governing.statistician_name} "
                    f"({governing.statistician_credentials}); approved "
                    f"method: {governing.method_description}; approval "
                    f"document: {governing.document_reference}; entered by "
                    f"{governing.entered_by} at "
                    f"{governing.entered_at.isoformat()}. The figure was "
                    f"factored up by {factor_applied} (counted x operated / "
                    f"(operated - missing)) and carries this attestation in "
                    f"its detail permanently. Revoking the attestation never "
                    f"deletes this record; it prevents FUTURE runs from "
                    f"factoring under it."
                ),
                # Missing trips have, by definition, no passenger-event
                # records to cite; the attestation row is named above.
                source_record_ids=(),
                # The factored-over trips travel with the finding (handoff
                # 0029) — an auditor asking "which trips did this cover?"
                # gets blocks, routes and times, not a truncated id list.
                subject=SubjectRef(kind=SUBJECT_TRIPS, ids=tuple(missing)),
            )
        )
    elif above_threshold:
        # The finding is addressed to a dispatcher, so it leads with what
        # happened in their words and hands the affected trips over as
        # STRUCTURED data (the subject ref) instead of pasting raw ids into
        # prose — handoff 0029. A 100% finding gets a different opening
        # sentence from a 3% one, because they have different causes and
        # different next actions.
        all_affected = missing_count == operated_count
        if all_affected:
            title = (
                f"No passenger counts arrived for any operated trip: all "
                f"{operated_count:,} trips in this period"
            )
            opening = (
                f"Every operated trip in this period is affected — all "
                f"{operated_count:,} of the trips Headway saw running have no "
                f"passenger counts at all. When the share is 100%, the cause "
                f"is almost never the individual trips: it usually means no "
                f"passenger-count data reached Headway for this period, so "
                f"start with the feed rather than the trips. Check whether "
                f"the automatic passenger counter feed (or the drop folder "
                f"the counts arrive in) was delivering on these dates before "
                f"working any trip individually."
            )
        else:
            title = (
                f"{missing_count:,} of {operated_count:,} operated trips have "
                f"no passenger counts ({_as_percent(missing_share)} — above "
                f"the FTA's 2% limit)"
            )
            opening = (
                f"{missing_count:,} of the {operated_count:,} trips Headway "
                f"saw running in this period have no passenger counts: "
                f"{_as_percent(missing_share)} of them "
                f"(share {missing_share}), which is more than the 2% the FTA "
                f"lets an agency fill in on its own."
            )
        blocking_issues = (
            Finding(
                issue_type="apc_missing_trips_above_fta_threshold",
                severity=SEVERITY_BLOCKING,
                title=title,
                description=(
                    f"{opening}\n\n"
                    f"Headway cannot report Unlinked Passenger Trips for this "
                    f"period until that is settled. Per the 2026 NTD Policy "
                    f"Manual p. 146, 'if the vehicle trips with missing data "
                    f"exceed 2 percent of total trips, agencies must have a "
                    f"qualified statistician approve the factoring method "
                    f"used to account for the missing percentage' — a human "
                    f"decision, so the calculation refuses to emit a value "
                    f"rather than estimate one ({missing_trip_threshold} is "
                    f"the FTA threshold, not an engineering placeholder). "
                    f"Either recover the missing counts, or record the "
                    f"statistician's approval as an attestation — the next "
                    f"run then factors up under it and the figure carries "
                    f"that approval permanently.\n\n"
                    f"All {missing_count:,} affected trips travel with this "
                    f"finding as structured data, so they can be shown "
                    f"grouped by block with each block's route and time of "
                    f"day instead of as a wall of identifiers."
                ),
                # Missing trips have, by definition, no passenger-event
                # records to cite — that is exactly why they need a SUBJECT:
                # source_record_ids is provenance, the subject is the thing a
                # person has to go find. Every affected trip is carried, not
                # a truncated sample.
                source_record_ids=(),
                subject=SubjectRef(kind=SUBJECT_TRIPS, ids=tuple(missing)),
            ),
        )
    else:
        # p. 146: "transit agencies should factor up the data to account for
        # the missing trips" — deterministic, FTA-sanctioned: counted x
        # operated/(operated - missing), from the EXACT fraction (the
        # quantized factor below is reporting provenance only), then
        # quantized to whole boardings.
        if missing_count == 0:
            exact_factor = Decimal(1)
            value = Decimal(counted_boardings).quantize(
                _UPT_QUANTUM, rounding=ROUND_HALF_EVEN
            )
        else:
            exact_factor = Decimal(operated_count) / Decimal(
                operated_count - missing_count
            )
            value = (
                Decimal(counted_boardings)
                * Decimal(operated_count)
                / Decimal(operated_count - missing_count)
            ).quantize(_UPT_QUANTUM, rounding=ROUND_HALF_EVEN)
        factor_applied = exact_factor.quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN
        )

    # Human-counted boardings join the figure AFTER the p. 146 factor-up and
    # never inside it (0.4.0). The factor accounts for TRIPS whose APC data is
    # missing; a no-run boarding is not a trip and was never in the operated
    # denominator, so scaling a human-confirmed head count by it would invent
    # riders nobody observed. Added to a refused (None) figure? No — a blocked
    # run stays blocked: a human decision does not cure a p. 146 refusal.
    if value is not None and human_revenue_boardings:
        value = (value + Decimal(human_revenue_boardings)).quantize(
            _UPT_QUANTUM, rounding=ROUND_HALF_EVEN
        )

    detail = UptDetail(
        total_boardings_counted=counted_boardings,
        operated_trips=operated_count,
        trips_with_events=trips_with_events_count,
        missing_trips=missing_count,
        missing_share=missing_share,
        factor_applied=factor_applied,
        source_mix=source_mix,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        attestation=attestation_provenance,
        excluded_non_revenue_boardings=excluded_non_revenue_boardings,
        pending_review_boardings=pending_review_boardings,
        human_revenue_boardings=human_revenue_boardings,
        human_non_revenue_boardings=human_non_revenue_boardings,
        human_classifications=tuple(human_classifications),
    )

    return CalcResult(
        value=value,
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=blocking_issues,
        warnings=tuple(warnings),
        infos=tuple(infos),
        detail=detail,
        review_items=tuple(review_items),
    )


def compute_upt_v0_3_0(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations: Iterable[AttestationContext] = (),
    revenue_windows: Mapping[date, RevenueWindow] | None = None,
) -> CalcResult:
    """upt_v0 0.3.0, RETAINED runnable (the sscls convention — shipped
    versions stay reproducible; handoff 0040).

    0.3.0 predates the review queue: it is compute_upt with NO recorded human
    decisions, so every ambiguous no-run boarding is held pending exactly as
    0.3.0 held it and the output (value, findings, detail JSON) is
    byte-identical to 0.3.0's — the 0.4.0 change is strictly additive (the
    human keys appear in the detail only when somebody classified something,
    which cannot happen here). Recomputing a figure certified under 0.3.0
    therefore reproduces it exactly, whatever has been decided since.
    """
    result = compute_upt(
        events,
        operated_trip_ids,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        attestations=attestations,
        revenue_windows=revenue_windows,
        boarding_reviews=None,
    )
    return dataclasses.replace(result, calc_version="0.3.0")


def _without_classification(
    events: Iterable[PassengerEvent],
) -> list[PassengerEvent]:
    """Events with revenue_classification cleared — the pre-0040 view.

    The retained 0.1.0/0.2.0 versions predate migration 0039; they must
    recompute BYTE-FOR-BYTE regardless of what a caller passes, so any
    assignment status on the input is stripped and the events are read purely
    through the trip-assignment proxy exactly as those versions always did.
    (A historical recompute normally passes pre-0040 events where the field
    is already None, so this is a belt-and-braces guarantee, not a rewrite of
    history.)
    """
    return [
        e if e.revenue_classification is None
        else dataclasses.replace(e, revenue_classification=None)
        for e in events
    ]


def compute_upt_v0_2_0(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations: Iterable[AttestationContext] = (),
) -> CalcResult:
    """upt_v0 0.2.0, RETAINED runnable (the sscls convention — shipped
    versions stay reproducible; handoff 0040).

    0.2.0 predates revenue classification: it is compute_upt with no
    revenue_windows and every input's assignment status stripped, so the
    no-run split never appears and the output (values, findings, detail JSON)
    is byte-identical to 0.2.0's — the 0.3.0 change is strictly additive (the
    revenue_classification detail block and the no-run findings appear only
    when a classified boarding exists, which cannot happen here). Pinned by
    tests/test_upt.py.
    """
    result = compute_upt(
        _without_classification(events),
        operated_trip_ids,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        attestations=attestations,
        revenue_windows=None,
    )
    return dataclasses.replace(result, calc_version="0.2.0")


def compute_upt_v0_1_0(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
) -> CalcResult:
    """upt_v0 0.1.0, RETAINED runnable (the sscls convention — shipped
    versions stay reproducible; handoff 0019).

    0.1.0 predates statistician attestations AND revenue classification: it
    is compute_upt with no attestation context, no revenue windows, and every
    input's assignment status stripped — every output is byte-identical,
    because both later changes are strictly additive (the attestation and
    revenue_classification detail keys are emitted only when they apply, which
    can never happen here). Pinned by tests/test_upt_attestation.py.
    """
    result = compute_upt(
        _without_classification(events),
        operated_trip_ids,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        attestations=(),
        revenue_windows=None,
    )
    return dataclasses.replace(result, calc_version="0.1.0")
