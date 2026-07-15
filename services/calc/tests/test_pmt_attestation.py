"""pmt_v0 0.2.0 — the statistician-attestation factor-up path (handoff 0019).

Mirrors test_upt_attestation.py for the PMT semantics, plus the
PMT-specific rule: an attestation approves the FACTORING method — it never
makes an invalid load profile valid (the pp. 151-152 discard discipline
stands untouched on an attested run).
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.attestation import (
    P146_ATTESTATION_BASIS,
    AttestationContext,
)
from headway_calc.pmt import compute_pmt, compute_pmt_v0_1_0
from headway_calc.types import PassengerEvent, StopTime
from headway_calc.upt import ALIGHTING_EVENT_TYPE, BOARDING_EVENT_TYPE

T0 = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 7, 9)


def ev(pe_id, trip, seq, etype, count, second):
    return PassengerEvent(
        event_timestamp=T0.replace(second=second % 60, minute=second // 60),
        service_date=SERVICE_DATE,
        passenger_event_id=pe_id,
        vehicle_id="veh-1",
        trip_id=trip,
        trip_stop_sequence=seq,
        event_type=(
            BOARDING_EVENT_TYPE if etype == "b" else ALIGHTING_EVENT_TYPE
        ),
        event_count=count,
        source="tides",
        source_record_id=f"rec-{pe_id}",
    )


def stop(trip, stop_id, seq, lat, lon):
    return StopTime(
        trip_id=trip,
        stop_id=stop_id,
        stop_sequence=seq,
        latitude=lat,
        longitude=lon,
        shape_dist_traveled=None,
    )


def attestation(**overrides) -> AttestationContext:
    base = dict(
        attestation_id="att-7",
        statistician_name="Dr. R. Fisher",
        statistician_credentials="PhD statistics",
        method_description="Valid-trip expansion factoring",
        document_reference="dms://approvals/2026/pmt-factoring.pdf",
        metric="pmt",
        scope_pattern="agency",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 1),
        entered_by="certifier",
        entered_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        revoked_at=None,
    )
    base.update(overrides)
    return AttestationContext(**base)


#: ONE valid trip (2 passengers over one ~0.69-mile segment), ONE invalid
#: trip (negative load), EIGHT operated trips with no events at all:
#: unusable = 8 missing + 1 invalid of 10 operated → share 0.9 > 2%.
EVENTS = [
    ev("1", "trip-1", 1, "b", 2, 0),
    ev("2", "trip-1", 2, "a", 2, 1),
    # trip-2: alights before boarding → negative load → invalid.
    ev("3", "trip-2", 1, "a", 3, 2),
    ev("4", "trip-2", 2, "b", 3, 3),
]
STOPS = [
    stop("trip-1", "s1", 1, 42.0, -71.0),
    stop("trip-1", "s2", 2, 42.01, -71.0),
    stop("trip-2", "s1", 1, 42.0, -71.0),
    stop("trip-2", "s2", 2, 42.01, -71.0),
]
OPERATED = [f"trip-{i}" for i in range(1, 11)]


def test_without_attestation_refusal_is_byte_for_byte_0_1_0():
    new = compute_pmt(EVENTS, OPERATED, STOPS)
    old = compute_pmt_v0_1_0(EVENTS, OPERATED, STOPS)
    assert (new.calc_version, old.calc_version) == ("0.2.0", "0.1.0")
    assert dataclasses.replace(new, calc_version="x") == dataclasses.replace(
        old, calc_version="x"
    )
    assert new.value is None
    assert [f.issue_type for f in new.blocking_issues] == [
        "apc_missing_trips_above_fta_threshold"
    ]
    assert "attestation" not in new.detail.to_dict()


def test_with_attestation_factors_valid_trip_figure_and_keeps_exclusions():
    baseline_blocked = compute_pmt(EVENTS, OPERATED, STOPS)
    result = compute_pmt(EVENTS, OPERATED, STOPS, attestations=(attestation(),))
    assert result.blocking_issues == ()
    # counted = the VALID trip's miles; factor = 10/(10−8−1) = 10.
    counted = Decimal(result.detail.to_dict()["passenger_miles_counted"])
    assert counted > 0
    assert result.value == (counted * 10).quantize(Decimal("0.01"))
    detail = result.detail.to_dict()
    assert detail["factor_applied"] == "10.000000"
    assert detail["attestation"]["attestation_id"] == "att-7"
    assert detail["attestation"]["basis"] == P146_ATTESTATION_BASIS
    # The invalid trip stays EXCLUDED and warned — an attestation approves
    # the factoring method, never the invalid load profile.
    assert detail["invalid_trips"] == 1
    assert detail["invalid_trip_reasons"] == {"negative_load": 1}
    excluded = [
        f for f in result.warnings if f.issue_type == "pmt_invalid_trip_excluded"
    ]
    assert len(excluded) == 1
    assert excluded == [
        f
        for f in baseline_blocked.warnings
        if f.issue_type == "pmt_invalid_trip_excluded"
    ]
    # ONE attested info finding quoting p. 146 verbatim.
    attested = [
        f
        for f in result.infos
        if f.issue_type == "apc_missing_trips_attested_factor_up"
    ]
    assert len(attested) == 1
    assert P146_ATTESTATION_BASIS in attested[0].description
    assert "attestation #att-7" in attested[0].title


def test_revoked_or_wrong_metric_never_factors():
    revoked = attestation(revoked_at=datetime(2026, 7, 11, tzinfo=timezone.utc))
    assert (
        compute_pmt(EVENTS, OPERATED, STOPS, attestations=(revoked,)).value
        is None
    )
    with pytest.raises(ValueError, match="never applies outside"):
        compute_pmt(
            EVENTS, OPERATED, STOPS, attestations=(attestation(metric="upt"),)
        )


def test_retained_0_1_0_has_no_attestation_surface():
    import inspect

    assert "attestations" not in inspect.signature(
        compute_pmt_v0_1_0
    ).parameters
