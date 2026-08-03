"""Behavioral + guardrail tests for the Vanpool (VP mode) calcs
(headway_calc.vp, handoff 0042).

The load-bearing property under test: EVERY VP figure REFUSES over the
fleet-telematics contract, because telematics is measured vehicle movement,
not revenue service, and the FTA vanpool rules need inputs telematics cannot
supply (see the module docstring and REGULATORY_TRACKER.md's VP section). The
tests pin: the refusal + naming finding for each figure, the never-a-guessed-
number invariant, the honest observed-movement context detail, the
basis-conflict and unmeasured-series surfacing, the simulated-source rule,
and that persist refuses a refused result.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.persist import _METRIC_BY_CALC_NAME, persist_result
from headway_calc.types import VpTelematicsDay
from headway_calc.vp import (
    BASIS_CONFLICT_ISSUE,
    DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS,
    REFUSAL_UPT,
    REFUSAL_VOMS,
    REFUSAL_VRH,
    REFUSAL_VRM,
    SIMULATED_SOURCE_ISSUE,
    UNMEASURED_ISSUE,
    VP_CALC_VERSION,
    compute_vp_upt,
    compute_vp_voms,
    compute_vp_vrh,
    compute_vp_vrm,
)

_WS = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)
_WE = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)

ALL_FIGURES = (compute_vp_vrm, compute_vp_vrh, compute_vp_upt, compute_vp_voms)
FIGURE_REFUSALS = {
    "vp_vrm_v0": REFUSAL_VRM,
    "vp_vrh_v0": REFUSAL_VRH,
    "vp_upt_v0": REFUSAL_UPT,
    "vp_voms_v0": REFUSAL_VOMS,
}


def _distance_row(
    vehicle_id="van-1",
    basis="ecu_odometer",
    value="60000",
    source="samsara",
    record_id="rec-1",
    sample_count=10,
    first_value="1000000",
    service_date=date(2026, 7, 15),
):
    """A well-formed measured distance series (a cumulative-counter delta)."""
    v = None if value is None else Decimal(value)
    last_value = None if v is None else Decimal(first_value) + v
    return VpTelematicsDay(
        vehicle_id=vehicle_id,
        service_date=service_date,
        window_start=_WS,
        window_end=_WE,
        measure="distance",
        basis=basis,
        unit="meters",
        reading_kind="cumulative_counter",
        sample_count=sample_count,
        source=source,
        source_record_id=record_id,
        value=v,
        first_reading_at=datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc),
        first_reading_value=Decimal(first_value),
        last_reading_at=(
            datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc) if v is not None else None
        ),
        last_reading_value=last_value,
        max_sample_gap_seconds=60 if sample_count >= 2 else None,
    )


def _engine_row(value="43200", source="samsara", record_id="rec-e"):
    v = Decimal(value)
    return VpTelematicsDay(
        vehicle_id="van-1",
        service_date=date(2026, 7, 15),
        window_start=_WS,
        window_end=_WE,
        measure="engine_time",
        basis="ecu_engine_time",
        unit="seconds",
        reading_kind="cumulative_counter",
        sample_count=10,
        source=source,
        source_record_id=record_id,
        value=v,
        first_reading_at=datetime(2026, 7, 15, 7, 0, tzinfo=timezone.utc),
        first_reading_value=Decimal("8000000"),
        last_reading_at=datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc),
        last_reading_value=Decimal("8000000") + v,
        max_sample_gap_seconds=60,
    )


# ---------------------------------------------------------------------------
# The load-bearing property: every figure refuses, never a number.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fn", ALL_FIGURES)
def test_every_figure_refuses_with_value_none(fn):
    result = fn([_distance_row(), _engine_row()])
    assert result.value is None, "a VP figure must never emit a number in v0"
    assert result.calc_version == VP_CALC_VERSION
    assert len(result.blocking_issues) == 1
    assert result.blocking_issues[0].issue_type == FIGURE_REFUSALS[result.calc_name]
    assert result.detail.reportable is False
    assert result.detail.refusal_reason == FIGURE_REFUSALS[result.calc_name]
    # input_record_ids is empty: nothing was consumed into a (non-existent)
    # figure; the records are cited by the findings instead.
    assert result.input_record_ids == ()


@pytest.mark.parametrize("fn", ALL_FIGURES)
def test_refusal_names_missing_input_in_plain_language(fn):
    result = fn([_distance_row()])
    desc = result.blocking_issues[0].description
    # Plain-language, names the manual + what is missing (accessibility /
    # fail-loudly): a transit ops manager can read it.
    assert "MISSING:" in desc
    assert "p. " in desc  # a page cite to the manual


def test_refusal_holds_on_empty_input():
    """No rows still refuses — never a silent zero (the empty-input honesty)."""
    for fn in ALL_FIGURES:
        result = fn([])
        assert result.value is None
        assert len(result.blocking_issues) == 1
        assert result.detail.vehicle_days_seen == 0
        assert result.detail.observed_distance_meters is None
        assert result.detail.observed_engine_seconds is None


# ---------------------------------------------------------------------------
# Honest observed-movement context (never a reportable figure).
# ---------------------------------------------------------------------------


def test_observed_movement_recorded_as_context():
    rows = [
        _distance_row(value="60000", record_id="d1"),
        _engine_row(value="43200", record_id="e1"),
    ]
    detail = compute_vp_vrm(rows).detail
    assert detail.observed_distance_meters == "60000"
    assert detail.observed_engine_seconds == "43200"
    # Keyed measure:basis, not basis alone. Keyed by basis alone, a source
    # reporting distance AND engine time on one basis added METRES to SECONDS
    # in a single bucket (external adversarial review, 2026-08-01).
    assert detail.by_basis == {
        "distance:ecu_odometer": "60000",
        "engine_time:ecu_engine_time": "43200",
    }
    # ONE vehicle-day: the same van on the same date reporting two measures is
    # two SERIES. Counting series inflated the fleet an auditor is told was
    # observed.
    assert detail.vehicle_days_seen == 1


def test_unmeasured_series_is_stated_never_zeroed():
    """An absent value contributes nothing to the observed sum and is counted
    as unmeasured — never coerced to 0 movement (fail-loudly)."""
    rows = [
        _distance_row(value="60000", record_id="d1"),
        _distance_row(
            vehicle_id="van-2", value=None, record_id="d2", sample_count=1
        ),
    ]
    result = compute_vp_vrm(rows)
    assert result.detail.observed_distance_meters == "60000"  # not 60000+0
    assert result.detail.vehicle_days_unmeasured == 1
    unmeasured = [w for w in result.warnings if w.issue_type == UNMEASURED_ISSUE]
    assert len(unmeasured) == 1
    assert unmeasured[0].source_record_ids == ("d2",)


# ---------------------------------------------------------------------------
# Basis conflict — Shared Constraint 7: surfaced, never averaged.
# ---------------------------------------------------------------------------


def test_disagreeing_bases_raise_one_warning_never_averaged():
    rows = [
        _distance_row(basis="ecu_odometer", value="60000", record_id="ecu"),
        _distance_row(basis="gps_distance", value="60900", record_id="gps"),
    ]
    result = compute_vp_vrm(rows)
    conflicts = [w for w in result.warnings if w.issue_type == BASIS_CONFLICT_ISSUE]
    assert len(conflicts) == 1
    assert result.detail.basis_conflicts == 1
    # both bases kept distinct in the detail — never merged into one number
    assert result.detail.by_basis == {
        "distance:ecu_odometer": "60000",
        "distance:gps_distance": "60900",
    }
    # ...and there is NO headline total, because there is no honest one to
    # give. These are two measurements of ONE ~60 km day. Adding them claimed
    # the van drove 120,900 m (external adversarial review, 2026-08-01);
    # picking one would be silent basis substitution, which ADR-0013 makes
    # unrepresentable. So the single number is undefined and says so, and the
    # per-basis breakdown above carries the truth.
    assert result.detail.observed_distance_meters is None
    assert set(conflicts[0].source_record_ids) == {"ecu", "gps"}


def test_agreeing_bases_within_tolerance_no_conflict():
    rows = [
        _distance_row(basis="ecu_odometer", value="60000", record_id="ecu"),
        _distance_row(basis="gps_distance", value="60050", record_id="gps"),
    ]
    result = compute_vp_vrm(rows)  # 50 m < 100 m default tolerance
    assert result.detail.basis_conflicts == 0
    assert not [w for w in result.warnings if w.issue_type == BASIS_CONFLICT_ISSUE]


def test_conflict_tolerance_is_an_explicit_input():
    rows = [
        _distance_row(basis="ecu_odometer", value="60000", record_id="ecu"),
        _distance_row(basis="gps_distance", value="60900", record_id="gps"),
    ]
    tight = compute_vp_vrm(rows, basis_conflict_tolerance_meters=Decimal("100"))
    loose = compute_vp_vrm(rows, basis_conflict_tolerance_meters=Decimal("1000"))
    assert tight.detail.basis_conflicts == 1
    assert loose.detail.basis_conflicts == 0


def test_unmeasured_basis_cannot_conflict():
    """An absent value cannot disagree — only measured bases are compared."""
    rows = [
        _distance_row(basis="ecu_odometer", value="60000", record_id="ecu"),
        _distance_row(
            basis="gps_distance", value=None, record_id="gps", sample_count=1
        ),
    ]
    assert compute_vp_vrm(rows).detail.basis_conflicts == 0


# ---------------------------------------------------------------------------
# Simulated-source rule (handoff 0005) — independent of the refusal.
# ---------------------------------------------------------------------------


def test_simulated_source_always_flagged():
    result = compute_vp_vrm([_distance_row(source="samsara_simulated", record_id="s")])
    infos = [i for i in result.infos if i.issue_type == SIMULATED_SOURCE_ISSUE]
    assert len(infos) == 1
    assert result.detail.source_mix == {"samsara_simulated": 1}


def test_real_source_not_flagged_simulated():
    result = compute_vp_vrm([_distance_row(source="samsara", record_id="r")])
    assert not [i for i in result.infos if i.issue_type == SIMULATED_SOURCE_ISSUE]
    assert result.detail.source_mix == {"samsara": 1}


def test_mixed_source_flags_only_simulated_records():
    rows = [
        _distance_row(source="samsara", record_id="real"),
        _distance_row(vehicle_id="v2", source="samsara_simulated", record_id="sim"),
    ]
    result = compute_vp_vrm(rows)
    infos = [i for i in result.infos if i.issue_type == SIMULATED_SOURCE_ISSUE]
    assert len(infos) == 1
    assert infos[0].source_record_ids == ("sim",)
    assert result.detail.source_mix == {"samsara": 1, "samsara_simulated": 1}


# ---------------------------------------------------------------------------
# Persist refuses a refused result (the value=None guard).
# ---------------------------------------------------------------------------


def test_vp_calc_names_have_metric_mappings():
    for name in FIGURE_REFUSALS:
        assert name in _METRIC_BY_CALC_NAME


def test_persist_refuses_refused_vp_result():
    """persist_result must reject a value=None result — a VP refusal never
    becomes a metric_values row."""
    result = compute_vp_vrm([_distance_row()])

    class _Conn:
        def cursor(self):  # pragma: no cover - never reached
            raise AssertionError("persist must refuse before touching the DB")

    with pytest.raises(ValueError):
        persist_result(_Conn(), result, date(2026, 7, 1), date(2026, 8, 1), scope="mode:VP")


# ---------------------------------------------------------------------------
# Input contract guards (honesty wall at the type boundary).
# ---------------------------------------------------------------------------


def test_basis_cannot_cross_its_measure():
    with pytest.raises(ValueError):
        VpTelematicsDay(
            vehicle_id="v",
            service_date=date(2026, 7, 15),
            window_start=_WS,
            window_end=_WE,
            measure="distance",
            basis="ecu_engine_time",  # engine basis on a distance row
            unit="meters",
            reading_kind="cumulative_counter",
            sample_count=2,
            source="samsara",
            source_record_id="x",
        )


def test_naive_window_rejected():
    with pytest.raises(ValueError):
        VpTelematicsDay(
            vehicle_id="v",
            service_date=date(2026, 7, 15),
            window_start=datetime(2026, 7, 15, 4, 0),  # naive
            window_end=_WE,
            measure="distance",
            basis="ecu_odometer",
            unit="meters",
            reading_kind="cumulative_counter",
            sample_count=2,
            source="samsara",
            source_record_id="x",
        )


def test_default_tolerance_is_declared_placeholder():
    # Not an FTA number — an engineering placeholder, explicit and overridable.
    assert DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS == Decimal("100")
