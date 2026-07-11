"""Golden-dataset regression tests for the handoff-0009 mode dimension.

Fixture: tests/golden/mode_scope/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT an FTA-certified figure; regression
anchor only. Two modes (bus/subway) plus the NULL-mode 'unknown' bucket:
per-mode values sum EXACTLY to the fleet values for the additive metrics
vrm/vrh/upt on this fixture; voms is NOT additive (max, not sum). The
per-mode paths run the UNCHANGED calc versions — same math per subset.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import load_events, load_positions

from headway_calc.mode import (
    compute_upt_by_mode,
    compute_voms_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
    unknown_mode_finding,
)
from headway_calc.upt import compute_upt
from headway_calc.voms import compute_voms
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)


def _values(by_mode) -> dict:
    return {bucket: str(result.value) for bucket, result in by_mode.items()}


def test_golden_vrm_per_mode_values_and_exact_fleet_sum(
    mode_golden_fixture, mode_golden_expected
):
    positions = load_positions(mode_golden_fixture)
    by_mode = compute_vrm_by_mode(positions)
    fleet = compute_vrm(positions)

    assert _values(by_mode) == mode_golden_expected["per_mode"]["vrm"]
    assert str(fleet.value) == mode_golden_expected["fleet"]["vrm"]
    # Additive on this hand-designed fixture: 6.22 + 6.22 + 0.00 = 12.44.
    assert sum(r.value for r in by_mode.values()) == fleet.value
    # Unchanged calc version — input selection, not a semantics change.
    assert {r.calc_version for r in by_mode.values()} == {"0.2.0"}
    assert {r.calc_name for r in by_mode.values()} == {"vrm_v0"}


def test_golden_vrh_per_mode_values_and_exact_fleet_sum(
    mode_golden_fixture, mode_golden_expected
):
    positions = load_positions(mode_golden_fixture)
    by_mode = compute_vrh_by_mode(positions)
    fleet = compute_vrh(positions)

    assert _values(by_mode) == mode_golden_expected["per_mode"]["vrh"]
    assert str(fleet.value) == mode_golden_expected["fleet"]["vrh"]
    assert sum(r.value for r in by_mode.values()) == fleet.value
    assert {r.calc_version for r in by_mode.values()} == {"0.4.0"}
    # No block_id in the fixture: per-trip fallback documents itself per
    # bucket — one block_unavailable info each for bus/subway, none for the
    # unknown bucket (no in-trip positions there).
    assert [i.issue_type for i in by_mode["bus"].infos] == ["block_unavailable"]
    assert [i.issue_type for i in by_mode["subway"].infos] == ["block_unavailable"]
    assert by_mode["unknown"].infos == ()


def test_golden_upt_per_mode_values_and_exact_fleet_sum(
    mode_golden_fixture, mode_golden_expected
):
    positions = load_positions(mode_golden_fixture)
    events = load_events(mode_golden_fixture)
    by_mode = compute_upt_by_mode(events, positions)
    operated_fleet = sorted({p.trip_id for p in positions if p.trip_id is not None})
    fleet = compute_upt(events, operated_fleet)

    assert _values(by_mode) == mode_golden_expected["per_mode"]["upt"]
    assert str(fleet.value) == mode_golden_expected["fleet"]["upt"]
    assert sum(r.value for r in by_mode.values()) == fleet.value
    assert {r.calc_version for r in by_mode.values()} == {"0.1.0"}
    # The unassigned boarding (count 4) is outside the revenue proxy: the
    # unknown bucket's UPT is the degenerate 0, not an invented count.
    unknown = by_mode["unknown"]
    assert unknown.value == Decimal("0")
    assert unknown.detail.operated_trips == 0
    assert unknown.detail.total_boardings_counted == 0


def test_golden_voms_per_mode_values_and_non_additivity_bounds(
    mode_golden_fixture, mode_golden_expected
):
    positions = load_positions(mode_golden_fixture)
    by_mode = compute_voms_by_mode(positions, PERIOD_START, PERIOD_END)
    fleet = compute_voms(positions, PERIOD_START, PERIOD_END)

    assert _values(by_mode) == mode_golden_expected["per_mode"]["voms"]
    assert str(fleet.value) == mode_golden_expected["fleet"]["voms"]
    # VOMS is NOT additive across modes: only the bounds are invariant
    # (max <= fleet <= sum). Equality with the sum on this single-day
    # fixture is coincidence, not an invariant — see BASIS.md and the
    # property tests' max-!=-sum pin.
    per_mode_values = [r.value for r in by_mode.values()]
    assert max(per_mode_values) <= fleet.value <= sum(per_mode_values)
    # Single observed day of 31: every result warns partial observation.
    assert [w.issue_type for w in fleet.warnings] == ["voms_partial_observation"]


def test_golden_unknown_mode_finding_counts(
    mode_golden_fixture, mode_golden_expected
):
    positions = load_positions(mode_golden_fixture)
    events = load_events(mode_golden_fixture)
    finding = unknown_mode_finding(positions, events)
    exp = mode_golden_expected["unknown_mode"]

    assert finding is not None
    assert finding.issue_type == "unknown_mode_share"
    assert finding.severity == "info"
    assert (
        f"{exp['positions_unknown']} of {exp['positions_total']} vehicle positions"
        in finding.description
    )
    assert (
        f"{exp['events_unknown']} of {exp['events_total']} passenger events"
        in finding.description
    )
    assert set(finding.source_record_ids) == {"rec-x-00", "rec-x-01", "rec-e-x-1"}
