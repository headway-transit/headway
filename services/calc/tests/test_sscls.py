"""Tests for headway_calc.sscls (sscls_v0 0.1.1, handoff 0010 + the
addendum correction round).

Goldens: ALL EIGHT of the 2026 S&S Policy Manual's Example 4 scenarios,
hand-worked against the outcomes documented in REGULATORY_TRACKER.md
("Verified — Safety & Security reporting" + "S&S addendum — verbatim rules
for sscls") and handoff 0010 — the only permitted regulatory sources.

Plus: every threshold branch (incl. the 0.1.1 additions: the p. 22 Other
Safety Events two-injury exception, rail-collision injury threshold,
non-rail tow-away, rail grade-crossing, rail vehicle-contact assault,
runaway train, rail evacuation-to-ROW), the rail/non-rail gating, the
never-guess rules (None damage, exact Decimal comparison), the p. 14
one-report rule, non-major S&S-50 scope, the RETAINED 0.1.0 behavior
(bug pinned), and the record_classification SQL shape.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.sscls import (
    CALC_NAME,
    CALC_VERSION,
    EVENT_CATEGORIES,
    MAJOR,
    NON_MAJOR,
    NOT_REPORTABLE,
    OTHER_SAFETY_EVENT_CATEGORIES,
    PROPERTY_DAMAGE_THRESHOLD_USD,
    RAIL_MODES,
    SafetyEvent,
    classification_to_dict,
    classify_event,
    classify_event_v0_1_0,
    record_classification,
)

OCCURRED = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)


def make_event(**overrides) -> SafetyEvent:
    """A minimal no-threshold bus event; tests override what they assert."""
    fields = dict(
        event_id="evt-0001",
        occurred_at=OCCURRED,
        mode="bus",
        event_category="other",
        fatalities=0,
        injuries=0,
        property_damage_usd=None,
        serious_injury=False,
        substantial_damage=False,
        towed=False,
        evacuation_life_safety=False,
        assault_on_worker=False,
        involves_transit_vehicle=False,
        involves_second_rail_vehicle=False,
        grade_crossing=False,
        type_of_service=None,
        runaway_train=False,
        evacuation_to_rail_row=False,
    )
    fields.update(overrides)
    return SafetyEvent(**fields)


# --- Example 4 goldens (hand-worked against the documented outcomes) ----------


def test_golden_scenario_4a_two_injuries_major():
    """Handoff 0010: "Scenario A → major (2 injuries)". Hand-worked: a
    non-rail event with 2 persons immediately transported meets the Exhibit 5
    injury threshold ("Immediate transport away from the scene for medical
    attention for one or more persons", p. 16) → ONE major report."""
    verdict = classify_event(
        make_event(mode="bus", event_category="collision", injuries=2)
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_immediate_transport",)
    hit = verdict.threshold_hits[0]
    assert "2 person(s)" in hit.plain_language
    assert "Immediate transport away from the scene" in hit.citation
    assert "p. 16" in hit.citation


def test_golden_scenario_4b_rail_to_rail_collision_auto_reportable():
    """Tracker (p. 17): "rail-to-rail collisions automatically reportable
    (Example 4B)". Hand-worked: NO injuries, NO damage flags — the collision
    of two rail vehicles is reportable by itself."""
    verdict = classify_event(
        make_event(
            mode="rail",
            event_category="collision",
            involves_second_rail_vehicle=True,
            involves_transit_vehicle=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("rail_to_rail_collision",)
    assert "automatically reportable" in verdict.threshold_hits[0].plain_language
    assert "Example 4B" in verdict.threshold_hits[0].citation


def test_golden_scenario_4e_assault_with_vehicle_contact_is_collision():
    """Tracker (p. 17): "assault/homicide involving contact with a transit
    vehicle reportable as collision (Scenario E)". Hand-worked: an assault
    where the victim contacts a transit vehicle and one person is
    immediately transported → evaluated as a collision, major via the
    (non-rail) injury threshold; the Scenario E note travels as an
    explanation but is never a threshold."""
    verdict = classify_event(
        make_event(
            mode="bus",
            event_category="assault",
            involves_transit_vehicle=True,
            injuries=1,
        )
    )
    assert verdict.effective_category == "collision"
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_immediate_transport",)
    note = verdict.threshold_hits[0]
    assert note.threshold_id == "assault_with_vehicle_contact_is_collision"
    assert "Scenario E" in note.citation


def test_golden_scenario_4g_cyber_major_via_substantial_damage():
    """Tracker (Scenario G, p. 19): unauthorized access to agency servers
    disrupting operations meets the substantial-damage threshold and "is
    reportable as a Cyber Security Major Event." Hand-worked: category
    'cyber' + substantial_damage, no injuries, non-rail mode → major."""
    verdict = classify_event(
        make_event(mode="bus", event_category="cyber", substantial_damage=True)
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("cyber_substantial_damage",)
    assert "Cyber Security Major Event" in verdict.threshold_hits[0].plain_language
    assert "Scenario G" in verdict.threshold_hits[0].citation


def test_golden_scenario_4c_rail_maintenance_vehicle_collision_one_injury():
    """Addendum verbatim solution (pp. 18-19): "rail maintenance vehicle
    collides with a person in yard, one injury → 'reportable as a Rail
    Transit Collision (include one Other vehicle)'". Hand-worked: rail
    collision (the maintenance vehicle is a transit vehicle, non-revenue
    included per p. 18) meets "an injury … threshold" with ONE injury
    (p. 17 rail collision rule) → major."""
    verdict = classify_event(
        make_event(
            mode="rail",
            event_category="collision",
            injuries=1,
            involves_transit_vehicle=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_immediate_transport",)
    hit = verdict.threshold_hits[0]
    assert "Example 4C" in hit.citation
    assert "rail collisions" in hit.citation


def test_golden_scenario_4d_two_workers_injured_other_safety_event():
    """Addendum verbatim solution: "two workers injured maintaining rail
    infrastructure → 'reportable as an Other Safety Event' (two injuries —
    consistent with the p. 22 rule)". Hand-worked: rail-mode 'other'
    category event with 2 immediate transports meets the p. 22 two-injury
    Other Safety Event threshold → major."""
    verdict = classify_event(
        make_event(mode="rail", event_category="other", injuries=2)
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_two_or_more",)
    assert "two or more injured persons" in verdict.threshold_hits[0].citation


def test_golden_scenario_4f_pre_revenue_testing_fatality():
    """Addendum verbatim solution: "pre-revenue streetcar testing fatality
    → 'reportable to the NTD as a fatal rail collision.'" Hand-worked: a
    tram (streetcar) collision with one fatality meets the fatality
    threshold (all modes, revenue service or not, p. 18) → major."""
    verdict = classify_event(
        make_event(
            mode="tram",
            event_category="collision",
            fatalities=1,
            involves_transit_vehicle=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("fatality",)
    assert verdict.is_rail_mode is True


def test_golden_scenario_4h_two_bus_riders_injured_at_agency_event():
    """Addendum verbatim solution: "two Roadeo bus riders injured, EMS
    transport → 'Reportable as a Major Safety Event due to the involvement
    of a transit vehicle.'" Hand-worked: an agency-event occurrence aboard
    a bus (transit vehicle involved — in NTD scope) with TWO immediate
    transports meets the p. 22 two-injury threshold even as an Other
    Safety Event → major."""
    verdict = classify_event(
        make_event(
            mode="bus",
            event_category="other",
            injuries=2,
            involves_transit_vehicle=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_two_or_more",)


def test_golden_example_6c_rail_serious_injury_without_transport_vs_bus():
    """Addendum 2 (p. 23, Example 6C): a person struck by a train leaves
    the scene, is hospitalized more than 48 hours that evening for an
    internal injury → serious injury, reportable major — transport is NOT
    required ("Individuals with serious injuries may or may not have been
    transported", p. 21). "The same scenario resulting from a collision
    with a bus would not be reportable." Hand-worked: injuries=0 (no
    immediate transport), serious_injury=True."""
    rail = classify_event(
        make_event(
            mode="rail",
            event_category="collision",
            injuries=0,
            serious_injury=True,
            involves_transit_vehicle=True,
        )
    )
    assert rail.classification == MAJOR
    assert rail.thresholds_met == ("rail_serious_injury",)
    hit = rail.threshold_hits[0]
    assert "may or may not have been transported" in hit.citation
    assert "need NOT have been transported" in hit.plain_language

    bus = classify_event(
        make_event(
            mode="bus",
            event_category="collision",
            injuries=0,
            serious_injury=True,
            involves_transit_vehicle=True,
        )
    )
    assert bus.classification == NOT_REPORTABLE


def test_golden_example_6e_mental_health_transport_not_reportable():
    """Addendum 2 (p. 23, Example 6E): a mental-health transport with no
    associated event is not reportable. Hand-worked: per the p. 22
    exclusion the enterer counts injuries=0 (transport for an unrelated
    mental-health evaluation is not an injury — the API field hint says
    so); nothing else met → not_reportable."""
    verdict = classify_event(
        make_event(mode="bus", event_category="other", injuries=0)
    )
    assert verdict.classification == NOT_REPORTABLE
    assert verdict.thresholds_met == ()
    assert verdict.non_major_basis == ()


def test_golden_example_6f_spit_on_operator_ss50_not_ss40():
    """Addendum 2 (p. 23, Example 6F): a passenger spits on an operator,
    no medical transport → "not reported on the S&S-40. However, the
    assault on a transit worker is reported on the S&S-50 Monthly Summary
    form." Hand-worked: category assault, no vehicle contact, injuries=0,
    assault_on_worker=True → non_major with the assault-on-worker basis."""
    verdict = classify_event(
        make_event(
            mode="bus",
            event_category="assault",
            injuries=0,
            assault_on_worker=True,
        )
    )
    assert verdict.classification == NON_MAJOR
    assert verdict.thresholds_met == ()
    (basis,) = verdict.non_major_basis
    assert basis.threshold_id == "non_major_assault_on_worker"
    assert "do not require an injury" in basis.citation


def test_golden_example_7c_rail_collision_towaway_is_substantial_damage():
    """Addendum 2 (p. 27, Example 7C): a rail vehicle collides with a
    private vehicle, which is towed away → "Substantial damage." The
    threshold fires mechanically from category collision + towed on a rail
    mode, even with the substantial_damage flag unset."""
    verdict = classify_event(
        make_event(
            mode="tram",
            event_category="collision",
            involves_transit_vehicle=True,
            towed=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("rail_substantial_damage",)
    hit = verdict.threshold_hits[0]
    assert "Example 7C" in hit.citation
    assert "towed away" in hit.plain_language


# --- threshold branches --------------------------------------------------------


def test_fatality_is_major_on_every_mode():
    for mode in ("bus", "rail", "ferry", "subway"):
        verdict = classify_event(make_event(mode=mode, fatalities=1))
        assert verdict.classification == MAJOR
        assert "fatality" in verdict.thresholds_met
        assert "include suicides" in verdict.threshold_hits[-1].citation


def test_non_rail_property_damage_threshold_is_exact_decimal():
    at = classify_event(
        make_event(property_damage_usd=Decimal("25000"))
    )
    just_below = classify_event(
        make_event(property_damage_usd=Decimal("24999.99"))
    )
    assert at.classification == MAJOR
    assert at.thresholds_met == ("property_damage_25k",)
    assert "equal to or exceeding $25,000" in at.threshold_hits[0].citation
    assert just_below.classification == NOT_REPORTABLE
    assert PROPERTY_DAMAGE_THRESHOLD_USD == Decimal("25000")


def test_unassessed_damage_is_never_guessed_to_meet_the_threshold():
    verdict = classify_event(make_event(property_damage_usd=None))
    assert verdict.classification == NOT_REPORTABLE
    assert verdict.thresholds_met == ()


def test_rail_uses_serious_injury_and_substantial_damage_not_dollar_line():
    # Rail modes: the quoted rail criteria govern; the $25,000 line and the
    # immediate-transport injury threshold are labeled non-rail in the
    # tracker (documented interpretation, module docstring).
    dollar_only = classify_event(
        make_event(mode="rail", property_damage_usd=Decimal("30000"))
    )
    assert dollar_only.classification == NOT_REPORTABLE

    serious = classify_event(make_event(mode="rail", serious_injury=True))
    assert serious.classification == MAJOR
    assert serious.thresholds_met == ("rail_serious_injury",)
    assert "fingers, toes, or nose" in serious.threshold_hits[0].plain_language

    substantial = classify_event(
        make_event(mode="subway", substantial_damage=True)
    )
    assert substantial.classification == MAJOR
    assert substantial.thresholds_met == ("rail_substantial_damage",)
    assert "towing, rescue" in substantial.threshold_hits[0].plain_language


def test_rail_listed_event_single_injury_without_serious_criteria_non_major():
    # An immediate-transport injury on a rail mode in a LISTED non-collision
    # category (fire) that does NOT meet the rail serious-injury criteria →
    # S&S-50 injury-threshold event (p. 3). (A rail COLLISION with one
    # injury is major — Example 4C; an Other Safety Event needs two —
    # p. 22.)
    verdict = classify_event(
        make_event(mode="rail", event_category="fire", injuries=1)
    )
    assert verdict.classification == NON_MAJOR
    assert verdict.thresholds_met == ()
    assert [b.threshold_id for b in verdict.non_major_basis] == [
        "non_major_injury_event",
        "non_major_fire",
    ]


def test_evacuation_life_safety_is_major_with_verbatim_citation():
    verdict = classify_event(make_event(evacuation_life_safety=True))
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("evacuation_life_safety",)
    assert (
        "Evacuation of a transit facility or vehicle for life-safety "
        "reasons" in verdict.threshold_hits[0].citation
    )


def test_derailment_is_major_for_rail_modes_only():
    rail = classify_event(make_event(mode="tram", event_category="derailment"))
    assert rail.classification == MAJOR
    assert rail.thresholds_met == ("derailment",)
    assert (
        "Both mainline and yard derailments and non-revenue vehicle "
        "derailments" in rail.threshold_hits[0].citation
    )
    # A non-rail 'derailment' entry meets no rail rule (data-entry oddity —
    # surfaced as not_reportable, never silently reclassified).
    bus = classify_event(make_event(mode="bus", event_category="derailment"))
    assert bus.classification == NOT_REPORTABLE


def test_rail_to_rail_requires_collision_category_and_second_rail_vehicle():
    no_second = classify_event(
        make_event(mode="rail", event_category="collision")
    )
    assert no_second.classification == NOT_REPORTABLE
    wrong_category = classify_event(
        make_event(mode="rail", event_category="security",
                   involves_second_rail_vehicle=True)
    )
    assert wrong_category.classification == NOT_REPORTABLE


def test_one_report_rule_multiple_thresholds_single_major_classification():
    # p. 14 (handoff 0010): >= 1 threshold met = ONE report. Every met
    # threshold is listed; the classification is a single 'major'.
    verdict = classify_event(
        make_event(
            mode="subway",
            event_category="collision",
            fatalities=1,
            serious_injury=True,
            substantial_damage=True,
            involves_second_rail_vehicle=True,
            evacuation_life_safety=True,
        )
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == (
        "fatality",
        "rail_serious_injury",
        "rail_substantial_damage",
        "rail_to_rail_collision",
        "evacuation_life_safety",
    )


# --- 0.1.1 addendum rules ---------------------------------------------------------


def test_other_safety_event_needs_two_injuries_single_is_non_major():
    """The 0.1.0 bug fix (p. 22): a single immediate-transport injury in an
    Other Safety Event with no other threshold is NON-major and belongs on
    the Non-Major Summary Report; two or more injuries are major."""
    single = classify_event(make_event(event_category="other", injuries=1))
    assert single.classification == NON_MAJOR
    assert single.thresholds_met == ()
    (basis,) = single.non_major_basis
    assert basis.threshold_id == "other_safety_event_single_injury"
    assert "Non-Major Summary Report" in basis.citation

    two = classify_event(make_event(event_category="other", injuries=2))
    assert two.classification == MAJOR
    assert two.thresholds_met == ("injury_two_or_more",)

    # The exception never weakens listed categories: one injury in a
    # non-rail collision or fire is still major (Exhibit 5, p. 16).
    for category in ("collision", "fire", "security"):
        listed = classify_event(
            make_event(event_category=category, injuries=1)
        )
        assert listed.classification == MAJOR, category
        assert "injury_immediate_transport" in listed.thresholds_met
    assert OTHER_SAFETY_EVENT_CATEGORIES == {"evacuation", "other"}


def test_other_safety_event_two_injury_rule_applies_on_rail_too():
    # Example 4D is a rail-mode Other Safety Event: the p. 22 rule is
    # mode-independent by its own text.
    verdict = classify_event(
        make_event(mode="subway", event_category="other", injuries=2)
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("injury_two_or_more",)


def test_non_rail_towaway_collision_is_major():
    # p. 17: non-rail collisions reportable when they "Involve a transit
    # revenue vehicle and the towing away of any vehicles (transit or
    # non-transit) from the scene".
    towed = classify_event(
        make_event(
            event_category="collision",
            involves_transit_vehicle=True,
            towed=True,
        )
    )
    assert towed.classification == MAJOR
    assert towed.thresholds_met == ("collision_towaway",)
    assert "towing away of any vehicles" in towed.threshold_hits[0].citation

    # Both conditions required: towed without a transit vehicle, or a
    # transit vehicle without a tow, meets nothing.
    assert (
        classify_event(
            make_event(event_category="collision", towed=True)
        ).classification
        == NOT_REPORTABLE
    )
    assert (
        classify_event(
            make_event(
                event_category="collision", involves_transit_vehicle=True
            )
        ).classification
        == NOT_REPORTABLE
    )
    # The tow-away rule is the NON-RAIL branch; a RAIL collision with a
    # tow-away meets the substantial-damage threshold instead (Example 7C,
    # addendum 2 — see the dedicated golden).
    rail_tow = classify_event(
        make_event(
            mode="rail",
            event_category="collision",
            involves_transit_vehicle=True,
            towed=True,
        )
    )
    assert rail_tow.classification == MAJOR
    assert rail_tow.thresholds_met == ("rail_substantial_damage",)


def test_rail_collision_at_grade_crossing_is_major():
    verdict = classify_event(
        make_event(mode="rail", event_category="collision", grade_crossing=True)
    )
    assert verdict.classification == MAJOR
    assert verdict.thresholds_met == ("rail_collision_grade_crossing",)
    assert (
        "Occur at a rail grade crossing or intersection"
        in verdict.threshold_hits[0].citation
    )
    # Non-rail grade-crossing flag alone meets nothing.
    bus = classify_event(
        make_event(event_category="collision", grade_crossing=True)
    )
    assert bus.classification == NOT_REPORTABLE


def test_rail_vehicle_contact_assault_needs_no_injury_non_rail_does():
    # p. 17 rail collisions "Include suicides, attempted suicides, and
    # assaults or homicides that involve contact with a transit vehicle" —
    # no injury qualifier on rail.
    rail = classify_event(
        make_event(
            mode="subway",
            event_category="assault",
            involves_transit_vehicle=True,
        )
    )
    assert rail.classification == MAJOR
    assert rail.thresholds_met == ("rail_collision_vehicle_contact_assault",)
    assert rail.effective_category == "collision"
    # Non-rail keeps the "resulting in an injury or fatality" qualifier:
    # contact alone (no injury, no tow) meets nothing.
    bus = classify_event(
        make_event(event_category="assault", involves_transit_vehicle=True)
    )
    assert bus.classification == NOT_REPORTABLE
    assert bus.effective_category == "collision"


def test_runaway_train_is_major_on_rail_only():
    rail = classify_event(make_event(mode="rail", runaway_train=True))
    assert rail.classification == MAJOR
    assert rail.thresholds_met == ("runaway_train",)
    assert (
        "uncommanded, uncontrolled, or unmanned"
        in rail.threshold_hits[0].citation
    )
    bus = classify_event(make_event(mode="bus", runaway_train=True))
    assert bus.classification == NOT_REPORTABLE


def test_rail_evacuation_to_controlled_row_is_major_on_rail_only():
    rail = classify_event(
        make_event(mode="tram", evacuation_to_rail_row=True)
    )
    assert rail.classification == MAJOR
    assert rail.thresholds_met == ("rail_evacuation_to_row",)
    assert (
        "Evacuations to controlled rail right-of-way"
        in rail.threshold_hits[0].citation
    )
    bus = classify_event(make_event(mode="bus", evacuation_to_rail_row=True))
    assert bus.classification == NOT_REPORTABLE


# --- retained 0.1.0 (bug pinned, never rewritten) ---------------------------------


def test_v0_1_0_retained_with_its_known_bug_and_without_addendum_rules():
    # The shipped 0.1.0 verdicts stay reproducible bit-for-bit: a
    # single-injury Other Safety Event was (wrongly) major under 0.1.0 —
    # pinned here as history, fixed in 0.1.1.
    single_injury_other = make_event(event_category="other", injuries=1)
    old = classify_event_v0_1_0(single_injury_other)
    assert old.classification == MAJOR
    assert old.thresholds_met == ("injury_immediate_transport",)
    assert old.calc_version == "0.1.0"
    new = classify_event(single_injury_other)
    assert new.classification == NON_MAJOR
    assert new.calc_version == "0.1.1"

    # 0.1.0 knows nothing of the addendum rules or the 0018 fields.
    runaway = make_event(mode="rail", runaway_train=True)
    assert classify_event_v0_1_0(runaway).classification == NOT_REPORTABLE
    towaway = make_event(
        event_category="collision", involves_transit_vehicle=True, towed=True
    )
    assert classify_event_v0_1_0(towaway).classification == NOT_REPORTABLE


# --- non-major (S&S-50 scope, p. 3) ---------------------------------------------


def test_assault_on_worker_without_injury_is_non_major():
    verdict = classify_event(
        make_event(event_category="assault", assault_on_worker=True)
    )
    assert verdict.classification == NON_MAJOR
    basis = verdict.non_major_basis[0]
    assert basis.threshold_id == "non_major_assault_on_worker"
    assert "do not require an injury" in basis.citation


def test_fire_without_thresholds_is_non_major():
    verdict = classify_event(make_event(event_category="fire"))
    assert verdict.classification == NON_MAJOR
    assert [b.threshold_id for b in verdict.non_major_basis] == [
        "non_major_fire"
    ]


def test_nothing_met_is_not_reportable():
    verdict = classify_event(make_event())
    assert verdict.classification == NOT_REPORTABLE
    assert verdict.thresholds_met == ()
    assert verdict.non_major_basis == ()
    assert "not NTD-reportable" in verdict.summary()


# --- invariants over the input space --------------------------------------------


def test_major_iff_thresholds_met_and_deterministic_over_flag_space():
    """Enumerate the boolean-flag space x categories x rail/non-rail modes
    (with fixed counts) and pin the structural invariants: major exactly
    when thresholds_met is non-empty (the migration-0017 CHECK), every
    explanation carries a citation naming the tracker, and classification
    is deterministic (same input twice → equal verdicts)."""
    flags = ("serious_injury", "substantial_damage", "evacuation_life_safety",
             "assault_on_worker", "involves_transit_vehicle",
             "involves_second_rail_vehicle", "grade_crossing", "towed",
             "runaway_train", "evacuation_to_rail_row")
    for mode in ("bus", "rail"):
        for category in EVENT_CATEGORIES:
            for values in itertools.product((False, True), repeat=len(flags)):
                overrides = dict(zip(flags, values))
                event = make_event(mode=mode, event_category=category, **overrides)
                for classify in (classify_event, classify_event_v0_1_0):
                    verdict = classify(event)
                    again = classify(event)
                    assert verdict == again
                    assert (verdict.classification == MAJOR) == bool(
                        verdict.thresholds_met
                    )
                    for hit in verdict.threshold_hits + verdict.non_major_basis:
                        assert "REGULATORY_TRACKER.md" in hit.citation
                    if verdict.classification == NON_MAJOR:
                        assert verdict.non_major_basis


def test_rail_modes_match_the_mr20_map():
    from headway_calc.mr20 import RAIL_MODES as MR20_RAIL_MODES

    assert RAIL_MODES == MR20_RAIL_MODES


# --- input validation (fail loudly) ---------------------------------------------


def test_event_refuses_naive_timestamp_bad_category_negative_counts():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_event(occurred_at=datetime(2026, 6, 15, 14, 30))
    with pytest.raises(ValueError, match="event_category"):
        make_event(event_category="explosion")
    with pytest.raises(ValueError, match="never be negative"):
        make_event(injuries=-1)
    with pytest.raises(ValueError, match="mode is required"):
        make_event(mode="")
    with pytest.raises(ValueError, match="Decimal"):
        make_event(property_damage_usd=25000.0)


# --- persistence (the only writer) ----------------------------------------------


class _RecordingConn:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        return (7, datetime(2026, 7, 12, tzinfo=timezone.utc))


def test_record_classification_sql_shape_and_version_string():
    conn = _RecordingConn()
    verdict = classify_event(make_event(fatalities=1))
    classification_id, classified_at = record_classification(conn, verdict)
    assert classification_id == 7
    (sql, params), = conn.executed
    assert "INSERT INTO safety.event_classifications" in sql
    assert "RETURNING classification_id, classified_at" in sql
    assert params == (
        "evt-0001",
        "major",
        ["fatality"],
        f"{CALC_NAME} {CALC_VERSION}",
    )


def test_classification_to_dict_is_json_safe_and_complete():
    import json

    verdict = classify_event(
        make_event(mode="rail", event_category="assault",
                   involves_transit_vehicle=True, assault_on_worker=True)
    )
    payload = classification_to_dict(verdict)
    json.dumps(payload)  # JSON-safe or it raises
    assert payload["classifier_name"] == "sscls_v0"
    assert payload["classifier_version"] == CALC_VERSION == "0.1.1"
    assert payload["effective_category"] == "collision"
    assert payload["is_rail_mode"] is True
    # 0.1.1: a rail vehicle-contact assault is major with no injury needed.
    assert payload["classification"] == "major"
    assert payload["thresholds_met"] == ["rail_collision_vehicle_contact_assault"]
    assert payload["summary"]
