"""otp_v0 + headway_adherence_v0 — OPERATIONS metrics (category 'ops').

THE HONESTY BOUNDARY (handoff 0014, design point 1): everything in this
module is an OPERATIONS metric, not a regulatory figure. Its results
persist with computed.metric_values.category = 'ops' (derived from the calc
registry in headway_calc.persist — a caller cannot mislabel them), can
never be certified (migration 0024's metric_values_ops_never_certified
CHECK), never appear in the MR-20/S&S packages or
/public/metrics/certified, and their definitions live in
services/calc/OPS_DEFINITIONS.md — the ops analogue of
REGULATORY_TRACKER.md, with the same quote-or-own-it discipline (TCQSM
citations where verified; explicitly Headway-owned formulas where not).

otp_v0 (0.1.0) — on-time performance
------------------------------------
Share (percent) of observed stop passages whose deviation from the
scheduled time lies inside the configurable window
[-early_tolerance_seconds, +late_tolerance_seconds]. Defaults 60/300 per
the TCQSM 3rd Edition typical fixed-route window (quoted in
OPS_DEFINITIONS.md); per-agency app.settings knobs
otp_early_tolerance_seconds / otp_late_tolerance_seconds (migration 0024)
with the same provenance discipline as coverage_threshold.

Schedule anchoring: GTFS stop_times are integer seconds after "noon minus
12 h" of the service day, LOCAL to the agency. The agency timezone comes
from canonical.agencies (migration 0026 — feed-declared, never a guess);
otp_v0 REFUSES (blocking) when it is absent or ambiguous. The service day
of an observed passage is resolved deterministically: among the local
dates {day before, same day, day after} of the observed instant, the one
whose scheduled instant lies closest to the observation wins — exact for
any delay/earliness under 12 h, documented in OPS_DEFINITIONS.md.

headway_adherence_v0 (0.1.0) — headway regularity (cvh)
-------------------------------------------------------
Coefficient of variation of headway deviations over consecutive OBSERVED
passage pairs at the same (route, direction, stop):

    cvh = pstdev(observed_headway_i − scheduled_headway_i)
          / mean(scheduled_headway_i)

Scheduled headway comes from the SAME pair's scheduled times (departure
preferred, arrival fallback), so no service calendar is required and
unobserved trips cannot silently distort the figure; pair exclusions are
counted in the detail, never silent. The math (including the exact
Fraction/Decimal evaluation — floating point never touches the figure) is
shown in OPS_DEFINITIONS.md.

Both calcs are pure, deterministic and stdlib-only. ``zoneinfo`` is stdlib;
its IANA data is a pinned input in deployment (the container image's
tzdata), the same determinism posture as the GTFS feed itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from zoneinfo import ZoneInfo

from headway_calc.passages import PassageDerivationStats
from headway_calc.types import (
    SEVERITY_BLOCKING,
    CalcResult,
    Finding,
    HeadwayAdherenceDetail,
    OtpDetail,
    StopPassage,
)

OTP_CALC_NAME = "otp_v0"
OTP_CALC_VERSION = "0.1.0"
HEADWAY_CALC_NAME = "headway_adherence_v0"
HEADWAY_CALC_VERSION = "0.1.0"

#: The configurable on-time window defaults (seconds). Basis: TCQSM 3rd
#: Edition typical fixed-route window ("1 min early to 5 min late"),
#: quoted with page citation in OPS_DEFINITIONS.md; per-agency
#: app.settings knobs (migration 0024) override per run.
OTP_EARLY_TOLERANCE_SECONDS = 60
OTP_LATE_TOLERANCE_SECONDS = 300

#: Scheduled gaps above this are service gaps (e.g. overnight), not
#: headways — a pair spanning one is excluded and counted. Headway-defined
#: (OPS_DEFINITIONS.md).
MAX_SCHEDULED_HEADWAY_SECONDS = 7200

#: Minimum sample sizes for a PER-ROUTE figure (Headway-defined,
#: OPS_DEFINITIONS.md): a route observed fewer times gets NO row — a
#: two-passage OTP would be numerically valid and practically meaningless.
#: Skipped routes are reported by routes_below_min_sample (the runner
#: routes them as one info finding), never silently absent.
MIN_PASSAGES_PER_ROUTE = 20
MIN_PAIRS_PER_ROUTE = 10

_QUANT_PERCENT = Decimal("0.01")
_QUANT_RATIO = Decimal("0.0001")
_QUANT_SECONDS = Decimal("0.01")

#: Ops route scope prefix (computed.metric_values.scope): 'route:<route_id>'
#: alongside the fleet-wide 'agency' rows. Passages on trips unknown to
#: canonical.trips bucket as 'route:unknown' — never dropped, never guessed.
ROUTE_UNKNOWN = "unknown"


def scope_for_route(route_id: str | None) -> str:
    return f"route:{route_id if route_id is not None else ROUTE_UNKNOWN}"


def _scheduled_seconds_otp(passage: StopPassage) -> int | None:
    """OTP compares against the published ARRIVAL where present (the rider
    promise at a stop), falling back to departure. None when the schedule
    row carries neither (non-timepoint) — skipped and counted, never
    interpolated."""
    if passage.scheduled_arrival_seconds is not None:
        return passage.scheduled_arrival_seconds
    return passage.scheduled_departure_seconds


def _scheduled_seconds_headway(passage: StopPassage) -> int | None:
    """Headways at a stop are DEPARTURE-to-departure where present (the
    interval a waiting rider experiences), falling back to arrival."""
    if passage.scheduled_departure_seconds is not None:
        return passage.scheduled_departure_seconds
    return passage.scheduled_arrival_seconds


def _scheduled_instant(
    service_date, seconds: int, zone: ZoneInfo
) -> datetime:
    """The UTC instant of a GTFS schedule time on one service date.

    GTFS convention: schedule times are seconds after "noon minus 12 h"
    LOCAL time of the service day — an anchor immune to DST transitions
    (verify against the GTFS Schedule Reference, gtfs.org; documented in
    OPS_DEFINITIONS.md)."""
    noon = datetime(
        service_date.year, service_date.month, service_date.day, 12,
        tzinfo=zone,
    )
    return noon - timedelta(hours=12) + timedelta(seconds=seconds)


def _deviation_seconds(
    passage: StopPassage, scheduled_seconds: int, zone: ZoneInfo
) -> int:
    """Signed deviation (observed − scheduled), resolving the service date
    deterministically: the candidate local date (day before / same / day
    after the observation's local date) whose scheduled instant lies
    closest to the observation wins. Exact for any deviation under 12 h;
    ties break to the earlier candidate (deterministic)."""
    local_date = passage.observed_time.astimezone(zone).date()
    best: int | None = None
    for day_offset in (-1, 0, 1):
        candidate = local_date + timedelta(days=day_offset)
        scheduled = _scheduled_instant(candidate, scheduled_seconds, zone)
        deviation = round(
            (passage.observed_time - scheduled).total_seconds()
        )
        if best is None or abs(deviation) < abs(best):
            best = deviation
    assert best is not None  # three candidates always evaluated
    return best


def _fraction_to_decimal(value: Fraction, quant: Decimal) -> Decimal:
    """Exact Fraction -> quantized Decimal (ROUND_HALF_EVEN via context
    default), evaluated at high precision so quantization is the only
    rounding step."""
    with localcontext() as ctx:
        ctx.prec = 50
        result = Decimal(value.numerator) / Decimal(value.denominator)
        return result.quantize(quant)


def _median(values: list[int]) -> Fraction:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return Fraction(ordered[mid])
    return Fraction(ordered[mid - 1] + ordered[mid], 2)


def compute_otp(
    passages: tuple[StopPassage, ...] | list[StopPassage],
    stats: PassageDerivationStats,
    agency_timezones: tuple[str, ...] | list[str],
    early_tolerance_seconds: int = OTP_EARLY_TOLERANCE_SECONDS,
    late_tolerance_seconds: int = OTP_LATE_TOLERANCE_SECONDS,
) -> CalcResult:
    """otp_v0: percent of observed passages on time (module docstring).

    ``agency_timezones`` — the DISTINCT canonical.agencies timezones
    (reader load_agency_timezones). Refuses (blocking) when empty or
    ambiguous: a schedule anchor is never guessed.
    """
    blocking: list[Finding] = []
    if len(agency_timezones) == 0:
        blocking.append(
            Finding(
                issue_type="agency_timezone_unknown",
                title="No agency timezone on file — OTP refused",
                description=(
                    "canonical.agencies holds no rows, so the agency "
                    "timezone that anchors GTFS schedule times is unknown. "
                    "Normalize a GTFS static feed (agency.txt, transform "
                    "normalize_gtfs_static >= 0.4.0, migration 0026) and "
                    "re-run. A timezone is never guessed."
                ),
                severity=SEVERITY_BLOCKING,
            )
        )
    elif len(set(agency_timezones)) > 1:
        blocking.append(
            Finding(
                issue_type="agency_timezone_ambiguous",
                title="Conflicting agency timezones on file — OTP refused",
                description=(
                    "canonical.agencies holds more than one distinct "
                    f"timezone ({', '.join(sorted(set(agency_timezones)))}); "
                    "the GTFS Schedule Reference requires one timezone per "
                    "feed, so this is a data problem to resolve — a "
                    "schedule anchor is never guessed."
                ),
                severity=SEVERITY_BLOCKING,
            )
        )
    if int(early_tolerance_seconds) < 0 or int(late_tolerance_seconds) < 0:
        raise ValueError(
            "otp tolerances must be >= 0 seconds (got "
            f"early={early_tolerance_seconds!r}, "
            f"late={late_tolerance_seconds!r})"
        )
    early = int(early_tolerance_seconds)
    late = int(late_tolerance_seconds)

    if blocking:
        return CalcResult(
            value=None,
            unit="percent",
            calc_name=OTP_CALC_NAME,
            calc_version=OTP_CALC_VERSION,
            input_record_ids=(),
            blocking_issues=tuple(blocking),
        )

    zone = ZoneInfo(agency_timezones[0])
    deviations: list[int] = []
    on_time = 0
    early_count = 0
    late_count = 0
    unscheduled = 0
    record_ids: set[str] = set()

    for passage in passages:
        scheduled = _scheduled_seconds_otp(passage)
        if scheduled is None:
            unscheduled += 1
            continue
        deviation = _deviation_seconds(passage, scheduled, zone)
        deviations.append(deviation)
        record_ids.add(passage.source_record_id)
        if deviation < -early:
            early_count += 1
        elif deviation > late:
            late_count += 1
        else:
            on_time += 1

    if not deviations:
        return CalcResult(
            value=None,
            unit="percent",
            calc_name=OTP_CALC_NAME,
            calc_version=OTP_CALC_VERSION,
            input_record_ids=(),
            blocking_issues=(
                Finding(
                    issue_type="no_observed_passages",
                    title="No supportable stop passages — OTP refused",
                    description=(
                        "The passage derivation produced no passage with a "
                        "scheduled time for this period/scope, so there is "
                        "nothing to measure on-time performance against. "
                        "The derivation's refusal accounting (cadence "
                        "evidence) is in the run's "
                        "ops_passage_derivation_summary finding. A figure "
                        "is never computed over nothing."
                    ),
                    severity=SEVERITY_BLOCKING,
                ),
            ),
        )

    total = len(deviations)
    value = _fraction_to_decimal(
        Fraction(100 * on_time, total), _QUANT_PERCENT
    )
    detail = OtpDetail(
        passages_considered=total,
        passages_unscheduled=unscheduled,
        on_time_count=on_time,
        early_count=early_count,
        late_count=late_count,
        deviation_mean_seconds=_fraction_to_decimal(
            Fraction(sum(deviations), total), _QUANT_SECONDS
        ),
        deviation_median_seconds=_fraction_to_decimal(
            _median(deviations), _QUANT_SECONDS
        ),
        early_tolerance_seconds=early,
        late_tolerance_seconds=late,
        agency_timezone=agency_timezones[0],
        derivation=stats.to_dict(),
    )
    return CalcResult(
        value=value,
        unit="percent",
        calc_name=OTP_CALC_NAME,
        calc_version=OTP_CALC_VERSION,
        input_record_ids=tuple(sorted(record_ids)),
        blocking_issues=(),
        detail=detail,
    )


def compute_otp_by_route(
    passages: tuple[StopPassage, ...] | list[StopPassage],
    stats: PassageDerivationStats,
    agency_timezones: tuple[str, ...] | list[str],
    early_tolerance_seconds: int = OTP_EARLY_TOLERANCE_SECONDS,
    late_tolerance_seconds: int = OTP_LATE_TOLERANCE_SECONDS,
) -> dict[str, CalcResult]:
    """One otp_v0 result per route with >= MIN_PASSAGES_PER_ROUTE passages.

    Keys are route buckets (route_id, or 'unknown' for passages on trips
    canonical.trips does not know). Routes below the minimum sample get NO
    entry — report them via routes_below_min_sample, never silently."""
    by_route: dict[str, list[StopPassage]] = {}
    for passage in passages:
        bucket = (
            passage.route_id if passage.route_id is not None else ROUTE_UNKNOWN
        )
        by_route.setdefault(bucket, []).append(passage)
    return {
        route: compute_otp(
            rows, stats, agency_timezones,
            early_tolerance_seconds, late_tolerance_seconds,
        )
        for route, rows in sorted(by_route.items())
        if len(rows) >= MIN_PASSAGES_PER_ROUTE
    }


def _headway_pairs(
    passages: list[StopPassage],
) -> tuple[list[tuple[int, int]], int, int, int]:
    """Consecutive-pair (scheduled_headway, observed_headway) extraction at
    ONE (route, direction, stop) group, passages sorted by observed_time.

    Returns (pairs, excluded_unscheduled, excluded_inverted,
    excluded_over_cap)."""
    ordered = sorted(
        passages,
        key=lambda p: (p.observed_time, p.trip_id, p.source_record_id),
    )
    pairs: list[tuple[int, int]] = []
    unscheduled = 0
    inverted = 0
    over_cap = 0
    for a, b in zip(ordered, ordered[1:]):
        s_a = _scheduled_seconds_headway(a)
        s_b = _scheduled_seconds_headway(b)
        if s_a is None or s_b is None:
            unscheduled += 1
            continue
        scheduled = s_b - s_a
        observed = round((b.observed_time - a.observed_time).total_seconds())
        if scheduled <= 0 or observed <= 0:
            inverted += 1
            continue
        if scheduled > MAX_SCHEDULED_HEADWAY_SECONDS:
            over_cap += 1
            continue
        pairs.append((scheduled, observed))
    return pairs, unscheduled, inverted, over_cap


def compute_headway_adherence(
    passages: tuple[StopPassage, ...] | list[StopPassage],
    stats: PassageDerivationStats,
) -> CalcResult:
    """headway_adherence_v0: cvh over consecutive observed pairs (module
    docstring; math in OPS_DEFINITIONS.md). Lower is steadier; TCQSM reads
    cvh against its LOS bands — Headway serves the number, not a grade."""
    groups: dict[tuple[str, int | None, str], list[StopPassage]] = {}
    for passage in passages:
        bucket = (
            passage.route_id if passage.route_id is not None else ROUTE_UNKNOWN
        )
        groups.setdefault(
            (bucket, passage.direction_id, passage.stop_id), []
        ).append(passage)

    pairs: list[tuple[int, int]] = []
    pair_records: set[str] = set()
    unscheduled = 0
    inverted = 0
    over_cap = 0
    stops_covered: set[str] = set()
    routes_covered: set[str] = set()
    for key in sorted(
        groups, key=lambda k: (k[0], -1 if k[1] is None else k[1], k[2])
    ):
        group_pairs, g_unsched, g_inv, g_cap = _headway_pairs(groups[key])
        unscheduled += g_unsched
        inverted += g_inv
        over_cap += g_cap
        if group_pairs:
            pairs.extend(group_pairs)
            stops_covered.add(key[2])
            routes_covered.add(key[0])
            pair_records.update(
                p.source_record_id for p in groups[key]
            )

    if not pairs:
        return CalcResult(
            value=None,
            unit="ratio",
            calc_name=HEADWAY_CALC_NAME,
            calc_version=HEADWAY_CALC_VERSION,
            input_record_ids=(),
            blocking_issues=(
                Finding(
                    issue_type="no_headway_pairs",
                    title="No usable consecutive passage pairs — headway adherence refused",
                    description=(
                        "No (route, direction, stop) group yielded a "
                        "consecutive observed passage pair with positive "
                        "scheduled and observed headways under the "
                        f"{MAX_SCHEDULED_HEADWAY_SECONDS} s scheduled cap, "
                        "so there is no headway to measure. The derivation's "
                        "refusal accounting is in the run's "
                        "ops_passage_derivation_summary finding. A figure "
                        "is never computed over nothing."
                    ),
                    severity=SEVERITY_BLOCKING,
                ),
            ),
        )

    n = len(pairs)
    deviations = [obs - sched for sched, obs in pairs]
    mean_dev = Fraction(sum(deviations), n)
    variance = (
        sum((Fraction(d) - mean_dev) ** 2 for d in deviations) / n
    )  # population variance, exact
    mean_scheduled = Fraction(sum(sched for sched, _ in pairs), n)

    with localcontext() as ctx:
        ctx.prec = 50
        stddev = (
            Decimal(variance.numerator) / Decimal(variance.denominator)
        ).sqrt()
        mean_sched_dec = Decimal(mean_scheduled.numerator) / Decimal(
            mean_scheduled.denominator
        )
        cvh = (stddev / mean_sched_dec).quantize(_QUANT_RATIO)
        stddev_out = stddev.quantize(_QUANT_SECONDS)

    detail = HeadwayAdherenceDetail(
        pairs_counted=n,
        pairs_excluded_unscheduled=unscheduled,
        pairs_excluded_inverted=inverted,
        pairs_excluded_over_cap=over_cap,
        stops_covered=len(stops_covered),
        routes_covered=len(routes_covered),
        mean_scheduled_headway_seconds=_fraction_to_decimal(
            mean_scheduled, _QUANT_SECONDS
        ),
        stddev_deviation_seconds=stddev_out,
        max_scheduled_headway_seconds=MAX_SCHEDULED_HEADWAY_SECONDS,
        derivation=stats.to_dict(),
    )
    return CalcResult(
        value=cvh,
        unit="ratio",
        calc_name=HEADWAY_CALC_NAME,
        calc_version=HEADWAY_CALC_VERSION,
        input_record_ids=tuple(sorted(pair_records)),
        blocking_issues=(),
        detail=detail,
    )


def compute_headway_adherence_by_route(
    passages: tuple[StopPassage, ...] | list[StopPassage],
    stats: PassageDerivationStats,
) -> dict[str, CalcResult]:
    """One headway_adherence_v0 result per route whose passages yield >=
    MIN_PAIRS_PER_ROUTE usable pairs (checked by computing — the pair
    count, not the passage count, is the sample)."""
    by_route: dict[str, list[StopPassage]] = {}
    for passage in passages:
        bucket = (
            passage.route_id if passage.route_id is not None else ROUTE_UNKNOWN
        )
        by_route.setdefault(bucket, []).append(passage)
    results: dict[str, CalcResult] = {}
    for route, rows in sorted(by_route.items()):
        result = compute_headway_adherence(rows, stats)
        if (
            result.value is not None
            and result.detail is not None
            and result.detail.pairs_counted >= MIN_PAIRS_PER_ROUTE
        ):
            results[route] = result
    return results


def routes_below_min_sample(
    passages: tuple[StopPassage, ...] | list[StopPassage],
) -> dict[str, int]:
    """Route buckets with observed passages but fewer than
    MIN_PASSAGES_PER_ROUTE — the runner reports them in ONE info finding so
    a per-route figure's absence is loud, never a silent gap."""
    counts: dict[str, int] = {}
    for passage in passages:
        bucket = (
            passage.route_id if passage.route_id is not None else ROUTE_UNKNOWN
        )
        counts[bucket] = counts.get(bucket, 0) + 1
    return {
        route: n
        for route, n in sorted(counts.items())
        if n < MIN_PASSAGES_PER_ROUTE
    }
