"""Safety & Security major-event classifier — sscls_v0 (handoff 0010).

Pure, deterministic events→classification per the 2026 S&S Policy Manual's
Exhibit 5 (p. 16) and pp. 17-22 event rules EXACTLY as quoted in
REGULATORY_TRACKER.md ("Verified — Safety & Security reporting, verified
2026-07-12" plus the "S&S addendum — verbatim rules for sscls" second-pass
section) — the ONLY permitted source of regulatory facts here. Every
threshold below carries the tracker quote it implements; no regulatory
number enters this module from memory.

Current version 0.1.1 (the addendum correction round). 0.1.0 is RETAINED
RUNNABLE as ``classify_event_v0_1_0`` (tracker rule: shipped versions are
never deleted or rewritten — live safety.event_classifications rows carry
'sscls_v0 0.1.0' and must stay reproducible). The 0.1.0 → 0.1.1 behavior
changes, each cited to the addendum:

- **Other Safety Events exception (p. 22) — the 0.1.0 bug fix.** Events
  that are NOT collisions, fires, security events, hazardous material
  spills, acts of God, or derailments (slips, trips, falls, smoke, fumes,
  electric shock, …) are major only on fatality, evacuation, property
  damage, or TWO or more injured persons; a single immediate-transport
  injury with no other threshold "is reported on the Non-Major Summary
  Report". 0.1.0 over-classified single-injury Other Safety Events as
  major.
- **Rail collision injury threshold (p. 17 / Example 4C):** a rail
  collision meeting "an injury … threshold" is reportable — one
  immediate-transport injury suffices (0.1.0 gated all rail injuries on the
  serious-injury criteria).
- **Non-rail tow-away collisions (p. 17):** "Involve a transit revenue
  vehicle and the towing away of any vehicles (transit or non-transit)
  from the scene" — ``towed`` is now a threshold condition, not just a
  supporting field.
- **Rail collision at a grade crossing (p. 17):** "Occur at a rail grade
  crossing or intersection" — the ``grade_crossing`` field is now a rail
  collision threshold condition.
- **Rail vehicle-contact assaults (p. 17):** rail collisions "Include
  suicides, attempted suicides, and assaults or homicides that involve
  contact with a transit vehicle" — no injury required on rail (non-rail
  keeps the "resulting in an injury or fatality" qualifier via the
  ordinary thresholds over the effective collision).
- **Runaway train (p. 17, rail, revenue vehicles; migration 0018 field):**
  "movement of a rail transit vehicle on the mainline, yard, or shop that
  is uncommanded, uncontrolled, or unmanned due to an incapacitated,
  sleeping, or absent operator, or the failure of a rail transit vehicle's
  electrical, mechanical, or software system or subsystem."
- **Rail evacuation to controlled right-of-way (p. 17; migration 0018
  field):** "Evacuations to controlled rail right-of-way (excludes
  evacuation to a platform, except for life safety)", covering "Both
  transit-directed evacuations and self-evacuations."
- **Derailments (p. 17, rail):** now cited verbatim — "Both mainline and
  yard derailments and non-revenue vehicle derailments."

Third-pass changes (tracker "S&S addendum 2 — damage + injury definitions
verbatim"), still within 0.1.1 (nothing between the passes shipped):

- **Rail serious injury (p. 21):** criteria now cited verbatim;
  automatically reportable, and transport is NOT required — "Individuals
  with serious injuries may or may not have been transported." The flag
  triggers independent of the injuries count on rail; it does nothing on
  non-rail modes (Example 6C: the same facts with a bus are not
  reportable).
- **Rail collision tow-away = substantial damage (Example 7C, p. 27):** a
  rail collision in which any vehicle is towed away meets the
  substantial-damage threshold mechanically, even when the
  substantial_damage flag was not set. (Example 7B — rescue train
  dispatched — has no capture field; the substantial_damage flag's
  "rescue" wording covers it at entry.)
- **Substantial-damage exclusions (p. 25)** (cracked windows; dents,
  bends, small punctures; broken lights/mirrors; own-power removal for
  minor repair/testing/recorder download) and the **property-damage
  summing rule (p. 25:** all involved property plus wreckage clearing,
  Example 7A) govern what the enterer records — surfaced in the
  explanation text and the API field hints, never silent logic.

Mode dependence: Exhibit 5 groups thresholds by rail vs non-rail/ferry
modes. The event's mode is AGENCY-SUPPLIED (Predominant Use Rule, p. 15:
multi-mode events are reported in ONE mode — rail wins over non-rail;
otherwise by passenger volume — the enterer applies the rule, this module
never infers a mode). Rail-ness is decided against RAIL_MODES — the
transform's GTFS route_type→mode map (the mr20.py precedent), an
ENGINEERING mapping of Headway's mode vocabulary, not an FTA list.

DOCUMENTED INTERPRETATIONS AND LIMITATIONS (handoff 0010 response):

- The tracker labels the injury threshold "(non-rail/ferry)" and the
  $25,000 property-damage threshold "(non-rail)": both apply to every
  NON-RAIL mode (ferry included); rail modes use the quoted rail
  serious-injury / substantial-damage criteria, PLUS the p. 17 rail
  collision injury threshold and the p. 22 two-injury Other Safety Event
  rule (mode-independent by its own text — Example 4D is rail).
- **Vocabulary gap ('other'):** hazardous material spills and acts of God
  are NOT Other Safety Events (p. 22) but Headway's category vocabulary
  has no value for them — entered as 'other' they would get the two-injury
  exception the manual does not give them. Flagged in the API field hint;
  open question (owner NTD role: category vocabulary increment).
- **"Involve an individual" (rail collisions, p. 17)** has no dedicated
  field; in practice a rail collision with a person meets the injury or
  fatality threshold (Example 4C arrives as one injury). Open question.
- **Suicide contact** is not separately capturable; a suicide by contact
  with a transit vehicle is entered as a collision (fatality/injury
  thresholds fire) or as an assault-with-contact. Documented, not inferred.
- p. 20 fatality nuances (illness/overdose/natural-cause deaths excluded;
  undetermined-cause deaths in a rail right-of-way reportable; 30-day
  confirmation) and p. 22 injury exclusions (transport solely for illness,
  natural causes, exposure, intoxication, overdose, or unrelated
  mental-health evaluation is not an injury; a collision-caused heart
  attack IS one) govern WHAT the enterer counts — surfaced as
  plain-language hints on the API entry fields, never silent logic.

Stdlib-only and pure (tests/test_purity.py): no clock, no randomness, no
driver import. ``record_classification`` is the ONLY writer of
safety.event_classifications (migration 0017's only-writer rule) — it takes
any DB-API 2.0 connection, the persist.py precedent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

CALC_NAME = "sscls_v0"
CALC_VERSION = "0.1.1"

MAJOR = "major"
NON_MAJOR = "non_major"
NOT_REPORTABLE = "not_reportable"

#: The manual's event vocabulary (handoff 0010 design point 1; migration
#: 0017 CHECK constraint). Cyber events are enterable citing Scenario G.
EVENT_CATEGORIES = (
    "collision",
    "derailment",
    "fire",
    "evacuation",
    "security",
    "assault",
    "cyber",
    "other",
)

#: p. 22 (addendum): Other Safety Events are "events that are NOT
#: collisions, fires, security events, hazardous material spills, acts of
#: God, or derailments". In Headway's vocabulary the non-Other (listed)
#: categories are collision/fire/security/assault/cyber/derailment;
#: 'evacuation' and 'other' classify under the Other Safety Events rules.
#: LIMITATION (module docstring): hazmat spills and acts of God have no
#: category of their own and would arrive as 'other'.
OTHER_SAFETY_EVENT_CATEGORIES = frozenset({"evacuation", "other"})

#: Rail-running mode strings per the transform's GTFS route_type→mode map —
#: the mr20.py precedent (headway_transform.gtfs_static.ROUTE_TYPE_TO_MODE,
#: route_types 0, 1, 2, 5, 7, 12). An ENGINEERING mapping of Headway's mode
#: vocabulary onto the manual's rail/non-rail grouping, not an FTA list.
RAIL_MODES = frozenset(
    {"tram", "subway", "rail", "cable_tram", "funicular", "monorail"}
)

#: Exhibit 5 (p. 16): property damage "equal to or exceeding $25,000"
#: (tracker quote, verified 2026-07-12). Exact Decimal, never float.
PROPERTY_DAMAGE_THRESHOLD_USD = Decimal("25000")

#: p. 22 (addendum): Other Safety Events meet the injury threshold only
#: when they "result in two or more injured persons".
OTHER_SAFETY_EVENT_INJURY_MINIMUM = 2

_TRACKER_POINTER = (
    "2026 S&S Policy Manual, verified 2026-07-12 — "
    "services/calc/REGULATORY_TRACKER.md, 'Verified — Safety & Security "
    "reporting'"
)

_ADDENDUM_POINTER = (
    "2026 S&S Policy Manual, verified 2026-07-12 second pass — "
    "services/calc/REGULATORY_TRACKER.md, 'S&S addendum — verbatim rules "
    "for sscls'"
)

_ADDENDUM2_POINTER = (
    "2026 S&S Policy Manual, verified 2026-07-12 third pass — "
    "services/calc/REGULATORY_TRACKER.md, 'S&S addendum 2 — damage + "
    "injury definitions verbatim'"
)


@dataclass(frozen=True)
class SafetyEvent:
    """One safety.events row (migrations 0017 + 0018) as the classifier's
    input.

    Frozen and validated: a malformed event refuses loudly at construction,
    never silently classifies. ``property_damage_usd`` None means the damage
    is NOT (yet) assessed — never coalesced to $0; the threshold then reads
    as not met and the explanation says so.
    """

    event_id: str
    occurred_at: datetime
    mode: str
    event_category: str
    fatalities: int
    injuries: int
    property_damage_usd: Decimal | None
    serious_injury: bool
    substantial_damage: bool
    towed: bool
    evacuation_life_safety: bool
    assault_on_worker: bool
    involves_transit_vehicle: bool
    involves_second_rail_vehicle: bool
    grade_crossing: bool
    type_of_service: str | None = None
    # Migration 0018 (addendum correction round). Default False so
    # 0.1.0-era inputs construct unchanged.
    runaway_train: bool = False
    evacuation_to_rail_row: bool = False

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError(
                f"SafetyEvent {self.event_id}: occurred_at must be "
                f"timezone-aware (got naive {self.occurred_at.isoformat()})."
            )
        if not self.mode:
            raise ValueError(
                f"SafetyEvent {self.event_id}: mode is required — the "
                f"Predominant Use Rule (p. 15) makes it the enterer's "
                f"explicit choice, never blank."
            )
        if self.event_category not in EVENT_CATEGORIES:
            raise ValueError(
                f"SafetyEvent {self.event_id}: unknown event_category "
                f"{self.event_category!r}; the manual's vocabulary is "
                f"{', '.join(EVENT_CATEGORIES)}."
            )
        if self.fatalities < 0 or self.injuries < 0:
            raise ValueError(
                f"SafetyEvent {self.event_id}: fatalities and injuries are "
                f"counts of people and can never be negative."
            )
        if self.property_damage_usd is not None:
            if not isinstance(self.property_damage_usd, Decimal):
                raise ValueError(
                    f"SafetyEvent {self.event_id}: property_damage_usd must "
                    f"be a Decimal (never float) or None when not assessed."
                )
            if self.property_damage_usd < 0:
                raise ValueError(
                    f"SafetyEvent {self.event_id}: property damage can "
                    f"never be negative."
                )


@dataclass(frozen=True)
class ThresholdHit:
    """One major-event threshold the event met: id, plain-language
    explanation (writable for a transit operations manager), and the
    citation of the tracker quote it implements."""

    threshold_id: str
    plain_language: str
    citation: str


@dataclass(frozen=True)
class SsClassification:
    """The classifier's deterministic verdict for one event."""

    event_id: str
    classification: str  # 'major' | 'non_major' | 'not_reportable'
    thresholds_met: tuple[str, ...]  # major thresholds only, evaluation order
    threshold_hits: tuple[ThresholdHit, ...]
    #: Why a non-major event is in S&S-50 scope (empty otherwise); each a
    #: (basis_id, plain_language, citation) ThresholdHit-shaped record.
    non_major_basis: tuple[ThresholdHit, ...]
    #: The category the rules were evaluated under: 'collision' for an
    #: assault involving contact with a transit vehicle (Scenario E),
    #: otherwise the entered category.
    effective_category: str
    is_rail_mode: bool
    calc_name: str = CALC_NAME
    calc_version: str = CALC_VERSION

    def summary(self) -> str:
        """One plain-language sentence for the entry response."""
        if self.classification == MAJOR:
            return (
                f"This event meets {len(self.thresholds_met)} major-event "
                f"threshold(s) and is ONE reportable major event (an event "
                f"meeting one or more thresholds is one report — p. 14): "
                f"an S&S-40 Major Event Report is due no later than 30 days "
                f"after the date of the event (Exhibit 2, p. 4)."
            )
        if self.classification == NON_MAJOR:
            return (
                "This event meets no major-event threshold but belongs on "
                "the S&S-50 Non-Major Monthly Summary for its month, mode, "
                "and type of service (p. 3)."
            )
        return (
            "This event meets no major-event threshold and none of the "
            "S&S-50 non-major criteria (injury-threshold events, non-major "
            "fires, assaults on a transit worker — p. 3). It is recorded "
            "but not NTD-reportable as entered."
        )


def _effective_category(event: SafetyEvent) -> tuple[str, ThresholdHit | None]:
    """Scenario E re-categorization: an assault involving contact with a
    transit vehicle is evaluated as a collision.

    Tracker quote (p. 17/19): "assault/homicide involving contact with a
    transit vehicle reportable as collision (Scenario E)".
    """
    if event.event_category == "assault" and event.involves_transit_vehicle:
        note = ThresholdHit(
            threshold_id="assault_with_vehicle_contact_is_collision",
            plain_language=(
                "This assault involved contact with a transit vehicle, so "
                "it is evaluated and reported as a collision."
            ),
            citation=(
                "p. 17 — 'assault/homicide involving contact with a transit "
                f"vehicle reportable as collision (Scenario E)' ({_TRACKER_POINTER})"
            ),
        )
        return "collision", note
    return event.event_category, None


def _is_other_safety_event(effective_category: str) -> bool:
    """p. 22 grouping over the EFFECTIVE category (an assault-with-contact
    is a collision, hence never an Other Safety Event)."""
    return effective_category in OTHER_SAFETY_EVENT_CATEGORIES


# --- shared threshold builders (identical text across retained versions) ------


def _fatality_hit(event: SafetyEvent) -> ThresholdHit:
    return ThresholdHit(
        threshold_id="fatality",
        plain_language=(
            f"{event.fatalities} person(s) died. Fatalities are those "
            f"confirmed within 30 days, and include suicides."
        ),
        citation=(
            "Exhibit 5, p. 16 — 'Confirmed within 30 days, and include "
            f"suicides.' ({_TRACKER_POINTER})"
        ),
    )


def _injury_immediate_transport_hit(
    event: SafetyEvent, *, rail_collision: bool
) -> ThresholdHit:
    if rail_collision:
        citation = (
            "p. 17 — rail collisions are reportable when they 'Meet an "
            "injury, fatality, substantial damage, or evacuation "
            "threshold' (Example 4C: one injury suffices) "
            f"({_ADDENDUM_POINTER})"
        )
    else:
        citation = (
            "Exhibit 5, p. 16 — 'Immediate transport away from the scene "
            f"for medical attention for one or more persons.' ({_TRACKER_POINTER})"
        )
    return ThresholdHit(
        threshold_id="injury_immediate_transport",
        plain_language=(
            f"{event.injuries} person(s) were taken directly from the "
            f"scene for medical care."
        ),
        citation=citation,
    )


def _property_damage_hit(event: SafetyEvent) -> ThresholdHit:
    return ThresholdHit(
        threshold_id="property_damage_25k",
        plain_language=(
            f"Estimated property damage of ${event.property_damage_usd} "
            f"is $25,000 or more (the estimate covers ALL property "
            f"involved — transit and non-transit — plus the cost of "
            f"clearing wreckage)."
        ),
        citation=(
            "Exhibit 5, p. 16 — property damage 'equal to or exceeding "
            "$25,000'; p. 25 — 'regardless of injuries or other "
            "thresholds', including 'the cost of clearing wreckage and "
            "damage to all other vehicles and property involved' "
            f"({_TRACKER_POINTER}; {_ADDENDUM2_POINTER})"
        ),
    )


def _rail_serious_injury_hit() -> ThresholdHit:
    return ThresholdHit(
        threshold_id="rail_serious_injury",
        plain_language=(
            "Someone suffered a rail serious injury — automatically "
            "reportable, and the person need NOT have been transported "
            "from the scene: hospitalization for more than 48 hours "
            "within 7 days of the event; a fracture of any bone (except "
            "simple fractures of fingers, toes, or nose); severe "
            "hemorrhages, or nerve, muscle, or tendon damage; an internal "
            "organ; or second- or third-degree burns, or any burns "
            "affecting more than 5 percent of the body surface."
        ),
        citation=(
            "p. 21 — rail serious-injury criteria, verbatim; "
            "'Individuals with serious injuries may or may not have been "
            f"transported.' ({_ADDENDUM2_POINTER})"
        ),
    )


def _rail_substantial_damage_hit(*, via_collision_tow: bool = False) -> ThresholdHit:
    if via_collision_tow:
        return ThresholdHit(
            threshold_id="rail_substantial_damage",
            plain_language=(
                "A rail collision in which a vehicle was towed away from "
                "the scene — towing away is substantial damage."
            ),
            citation=(
                "p. 27, Example 7C — a rail vehicle collides with a "
                "private vehicle, which is towed away → 'Substantial "
                f"damage.' ({_ADDENDUM2_POINTER})"
            ),
        )
    return ThresholdHit(
        threshold_id="rail_substantial_damage",
        plain_language=(
            "A rail vehicle, facility, equipment, rolling stock, or "
            "infrastructure sustained substantial damage: operations were "
            "disrupted AND structural strength, performance, or operating "
            "characteristics were adversely affected such that towing, "
            "rescue, on-site maintenance, or immediate removal prior to "
            "safe operation was required. (Cracked windows; dents, bends, "
            "or small puncture holes; broken lights or mirrors; or removal "
            "under the vehicle's own power for minor repair, maintenance, "
            "testing, or recorder download do NOT count.)"
        ),
        citation=(
            "p. 25 — rail substantial-damage definition and exclusions, "
            f"verbatim ({_ADDENDUM2_POINTER})"
        ),
    )


def _rail_to_rail_hit(*, addendum: bool) -> ThresholdHit:
    if addendum:
        citation = (
            "p. 17 — rail collisions 'Involve a rail transit vehicle and a "
            "second rail transit vehicle' (Example 4B: automatically "
            f"reportable) ({_ADDENDUM_POINTER})"
        )
    else:
        citation = (
            "p. 17 — 'rail-to-rail collisions automatically "
            f"reportable (Example 4B)' ({_TRACKER_POINTER})"
        )
    return ThresholdHit(
        threshold_id="rail_to_rail_collision",
        plain_language=(
            "A rail transit vehicle collided with another rail "
            "vehicle. Rail-to-rail collisions are automatically "
            "reportable, regardless of injuries or damage."
        ),
        citation=citation,
    )


def _cyber_hit() -> ThresholdHit:
    return ThresholdHit(
        threshold_id="cyber_substantial_damage",
        plain_language=(
            "A cyber event disrupted operations, meeting the "
            "substantial-damage threshold — reportable as a Cyber "
            "Security Major Event."
        ),
        citation=(
            "Scenario G, p. 19 — unauthorized access disrupting "
            "operations 'is reportable as a Cyber Security Major "
            f"Event.' ({_TRACKER_POINTER})"
        ),
    )


def _shared_non_major_basis(
    event: SafetyEvent, effective_category: str
) -> list[ThresholdHit]:
    """The p. 3 S&S-50 fire and assault-on-worker bases (identical across
    versions); injury bases are version-specific."""
    basis: list[ThresholdHit] = []
    if effective_category == "fire":
        basis.append(
            ThresholdHit(
                threshold_id="non_major_fire",
                plain_language=(
                    "A fire occurred without meeting a major-event threshold."
                ),
                citation=(
                    f"p. 3 — S&S-50 scope: non-major fires ({_TRACKER_POINTER})"
                ),
            )
        )
    if event.assault_on_worker:
        basis.append(
            ThresholdHit(
                threshold_id="non_major_assault_on_worker",
                plain_language=(
                    "A transit worker was assaulted. An injury is NOT "
                    "required for this to be reportable on the S&S-50."
                ),
                citation=(
                    "p. 3 — 'Assaults on a transit worker do not require an "
                    "injury to be reportable on the S&S-50.' "
                    f"({_TRACKER_POINTER})"
                ),
            )
        )
    return basis


def _verdict(
    event: SafetyEvent,
    hits: list[ThresholdHit],
    basis: list[ThresholdHit],
    notes: tuple[ThresholdHit, ...],
    effective_category: str,
    is_rail: bool,
    version: str,
) -> SsClassification:
    if hits:
        return SsClassification(
            event_id=event.event_id,
            classification=MAJOR,
            thresholds_met=tuple(h.threshold_id for h in hits),
            threshold_hits=notes + tuple(hits),
            non_major_basis=(),
            effective_category=effective_category,
            is_rail_mode=is_rail,
            calc_version=version,
        )
    if basis:
        return SsClassification(
            event_id=event.event_id,
            classification=NON_MAJOR,
            thresholds_met=(),
            threshold_hits=notes,
            non_major_basis=tuple(basis),
            effective_category=effective_category,
            is_rail_mode=is_rail,
            calc_version=version,
        )
    return SsClassification(
        event_id=event.event_id,
        classification=NOT_REPORTABLE,
        thresholds_met=(),
        threshold_hits=notes,
        non_major_basis=(),
        effective_category=effective_category,
        is_rail_mode=is_rail,
        calc_version=version,
    )


def classify_event(event: SafetyEvent) -> SsClassification:
    """Classify one safety event — sscls_v0 0.1.1 (the addendum correction
    round). Pure and deterministic: the same event always yields the same
    classification; thresholds evaluate in a fixed order and
    ``thresholds_met`` preserves it.
    """
    is_rail = event.mode in RAIL_MODES
    effective_category, category_note = _effective_category(event)
    is_other = _is_other_safety_event(effective_category)
    hits: list[ThresholdHit] = []

    # 1. Fatalities — all modes, all groups (Exhibit 5, p. 16). The p. 20
    #    nuances (natural-cause exclusions; undetermined-cause deaths in a
    #    rail ROW reportable; 30-day confirmation) govern what the enterer
    #    counts — surfaced as API field hints, not silent logic.
    if event.fatalities >= 1:
        hits.append(_fatality_hit(event))

    # 2. Injuries — group-dependent (the 0.1.1 correction):
    #    - Other Safety Events (p. 22): TWO or more injured persons, any
    #      mode (Example 4D is rail).
    #    - Listed categories, non-rail: one or more immediate transports
    #      (Exhibit 5, p. 16).
    #    - Listed categories, rail: collisions meet "an injury … threshold"
    #      (p. 17; Example 4C — one injury suffices); other rail listed
    #      events use the serious-injury criteria below.
    if is_other:
        if event.injuries >= OTHER_SAFETY_EVENT_INJURY_MINIMUM:
            hits.append(
                ThresholdHit(
                    threshold_id="injury_two_or_more",
                    plain_language=(
                        f"{event.injuries} people were taken directly from "
                        f"the scene for medical care. An Other Safety Event "
                        f"(not a collision, fire, security event, hazardous "
                        f"material spill, act of God, or derailment) is a "
                        f"major event when two or more persons are injured."
                    ),
                    citation=(
                        "p. 22 — Other Safety Events: 'Only report these "
                        "events when they meet either the fatality, "
                        "evacuation, or property damage threshold or result "
                        f"in two or more injured persons.' ({_ADDENDUM_POINTER})"
                    ),
                )
            )
    elif not is_rail and event.injuries >= 1:
        hits.append(_injury_immediate_transport_hit(event, rail_collision=False))
    elif (
        is_rail
        and effective_category == "collision"
        and event.injuries >= 1
    ):
        hits.append(_injury_immediate_transport_hit(event, rail_collision=True))

    # 3. Property damage — non-rail modes, all groups (p. 22 keeps the
    #    property-damage threshold for Other Safety Events). None (not
    #    assessed) never meets the threshold — a missing figure is never
    #    guessed. Rail modes use the substantial-damage criteria below.
    if (
        not is_rail
        and event.property_damage_usd is not None
        and event.property_damage_usd >= PROPERTY_DAMAGE_THRESHOLD_USD
    ):
        hits.append(_property_damage_hit(event))

    # 4./5. Rail serious injury and rail substantial damage — rail modes,
    #    any category (verbatim p. 21 / p. 25 criteria, addendum 2).
    #    Serious injury is automatically reportable and transport is NOT
    #    required ("Individuals with serious injuries may or may not have
    #    been transported", p. 21) — the flag triggers independent of the
    #    injuries count. Example 7C: a rail collision where any vehicle is
    #    towed away IS substantial damage — mechanical, even when the flag
    #    was not set.
    if is_rail and event.serious_injury:
        hits.append(_rail_serious_injury_hit())
    if is_rail and event.substantial_damage:
        hits.append(_rail_substantial_damage_hit())
    elif is_rail and effective_category == "collision" and event.towed:
        hits.append(_rail_substantial_damage_hit(via_collision_tow=True))

    # 6. Rail-to-rail collision — automatically reportable (p. 17,
    #    Example 4B).
    if (
        is_rail
        and effective_category == "collision"
        and event.involves_second_rail_vehicle
    ):
        hits.append(_rail_to_rail_hit(addendum=True))

    # 7. Rail collision at a grade crossing or intersection (p. 17).
    if is_rail and effective_category == "collision" and event.grade_crossing:
        hits.append(
            ThresholdHit(
                threshold_id="rail_collision_grade_crossing",
                plain_language=(
                    "A rail transit vehicle collided at a rail grade "
                    "crossing or intersection — reportable regardless of "
                    "injuries or damage."
                ),
                citation=(
                    "p. 17 — rail collisions are reportable when they "
                    f"'Occur at a rail grade crossing or intersection' ({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 8. Rail vehicle-contact assault/homicide (p. 17): reportable on rail
    #    with NO injury requirement (non-rail vehicle-contact assaults need
    #    a resulting injury or fatality — covered by the ordinary
    #    thresholds over the effective collision).
    if (
        is_rail
        and event.event_category == "assault"
        and event.involves_transit_vehicle
    ):
        hits.append(
            ThresholdHit(
                threshold_id="rail_collision_vehicle_contact_assault",
                plain_language=(
                    "An assault or homicide involved contact with a rail "
                    "transit vehicle — reportable as a rail collision "
                    "regardless of injuries."
                ),
                citation=(
                    "p. 17 — rail collisions 'Include suicides, attempted "
                    "suicides, and assaults or homicides that involve "
                    f"contact with a transit vehicle' ({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 9. Non-rail tow-away collision (p. 17): a transit revenue vehicle is
    #    involved and ANY vehicle is towed from the scene.
    if (
        not is_rail
        and effective_category == "collision"
        and event.involves_transit_vehicle
        and event.towed
    ):
        hits.append(
            ThresholdHit(
                threshold_id="collision_towaway",
                plain_language=(
                    "The collision involved a transit revenue vehicle and "
                    "at least one vehicle (transit or not) was towed away "
                    "from the scene."
                ),
                citation=(
                    "p. 17 — non-rail collisions are reportable when they "
                    "'Involve a transit revenue vehicle and the towing away "
                    "of any vehicles (transit or non-transit) from the "
                    f"scene' ({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 10. Evacuation for life safety — all modes (p. 17: non-rail
    #     "Evacuation of a transit facility or vehicle for life-safety
    #     reasons"; the rail rule includes it).
    if event.evacuation_life_safety:
        hits.append(
            ThresholdHit(
                threshold_id="evacuation_life_safety",
                plain_language=(
                    "People were evacuated from a transit facility or "
                    "vehicle for life-safety reasons."
                ),
                citation=(
                    "p. 17 — 'Evacuation of a transit facility or vehicle "
                    f"for life-safety reasons.' ({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 11. Rail evacuation to controlled right-of-way (p. 17; migration 0018
    #     field): reportable even without a life-safety reason; includes
    #     self-evacuations. Evacuation to a platform is NOT this threshold
    #     (except for life safety, which is #10).
    if is_rail and event.evacuation_to_rail_row:
        hits.append(
            ThresholdHit(
                threshold_id="rail_evacuation_to_row",
                plain_language=(
                    "People evacuated to the controlled rail right-of-way "
                    "(transit-directed or self-evacuation). Evacuation to a "
                    "platform does not count here unless it was for life "
                    "safety."
                ),
                citation=(
                    "p. 17 — rail: 'Evacuations to controlled rail "
                    "right-of-way (excludes evacuation to a platform, "
                    "except for life safety)', covering 'Both "
                    "transit-directed evacuations and self-evacuations.' "
                    f"({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 12. Derailment — rail modes, by entered category (p. 17 verbatim).
    if is_rail and event.event_category == "derailment":
        hits.append(
            ThresholdHit(
                threshold_id="derailment",
                plain_language=(
                    "A rail vehicle derailed. Mainline, yard, and "
                    "non-revenue vehicle derailments all count."
                ),
                citation=(
                    "p. 17 — derailments (rail): 'Both mainline and yard "
                    "derailments and non-revenue vehicle derailments.' "
                    f"({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 13. Runaway train — rail modes, revenue vehicles (p. 17; migration
    #     0018 field).
    if is_rail and event.runaway_train:
        hits.append(
            ThresholdHit(
                threshold_id="runaway_train",
                plain_language=(
                    "A rail transit revenue vehicle moved uncommanded, "
                    "uncontrolled, or unmanned (incapacitated, sleeping, or "
                    "absent operator, or an electrical, mechanical, or "
                    "software failure) on the mainline, in a yard, or in a "
                    "shop."
                ),
                citation=(
                    "p. 17 — Runaway Train: 'movement of a rail transit "
                    "vehicle on the mainline, yard, or shop that is "
                    "uncommanded, uncontrolled, or unmanned due to an "
                    "incapacitated, sleeping, or absent operator, or the "
                    "failure of a rail transit vehicle's electrical, "
                    "mechanical, or software system or subsystem.' "
                    f"({_ADDENDUM_POINTER})"
                ),
            )
        )

    # 14. Cyber substantial damage — any mode (Scenario G, p. 19).
    if event.event_category == "cyber" and event.substantial_damage:
        hits.append(_cyber_hit())

    # No major threshold met — S&S-50 non-major scope (p. 3), plus the
    # p. 22 single-injury Other Safety Event rule (the 0.1.1 fix's flip
    # side: those events belong EXPLICITLY on the Non-Major Summary).
    basis: list[ThresholdHit] = []
    if event.injuries >= 1:
        if is_other:
            basis.append(
                ThresholdHit(
                    threshold_id="other_safety_event_single_injury",
                    plain_language=(
                        f"{event.injuries} person(s) were taken directly "
                        f"from the scene for medical care in an Other "
                        f"Safety Event that met no major threshold — this "
                        f"belongs on the Non-Major Summary Report."
                    ),
                    citation=(
                        "p. 22 — 'Other Safety Events that result in one "
                        "person immediately transported from the scene for "
                        "medical attention but do not trigger any other "
                        "major reporting thresholds are reported on the "
                        f"Non-Major Summary Report.' ({_ADDENDUM_POINTER})"
                    ),
                )
            )
        else:
            basis.append(
                ThresholdHit(
                    threshold_id="non_major_injury_event",
                    plain_language=(
                        f"{event.injuries} person(s) were taken directly "
                        f"from the scene for medical care, without meeting "
                        f"a major-event threshold for this mode."
                    ),
                    citation=(
                        "p. 3 — S&S-50 scope: injury-threshold events "
                        f"({_TRACKER_POINTER})"
                    ),
                )
            )
    basis.extend(_shared_non_major_basis(event, effective_category))

    notes: tuple[ThresholdHit, ...] = (
        (category_note,) if category_note is not None else ()
    )
    return _verdict(
        event, hits, basis, notes, effective_category, is_rail, CALC_VERSION
    )


def classify_event_v0_1_0(event: SafetyEvent) -> SsClassification:
    """RETAINED 0.1.0 classifier (shipped 2026-07-12, first pass) — kept
    runnable so historical safety.event_classifications rows recompute
    bit-for-bit (tracker rule: shipped versions are never deleted or
    rewritten). KNOWN BUG, fixed in 0.1.1: single-injury Other Safety
    Events (p. 22) are over-classified as major; the p. 17 rail-collision
    injury, tow-away, grade-crossing, vehicle-contact, runaway-train, and
    evacuation-to-ROW rules are absent. Ignores the migration-0018 fields.
    Do not use for new classifications.
    """
    is_rail = event.mode in RAIL_MODES
    effective_category, category_note = _effective_category(event)
    hits: list[ThresholdHit] = []

    if event.fatalities >= 1:
        hits.append(_fatality_hit(event))
    if not is_rail and event.injuries >= 1:
        hits.append(_injury_immediate_transport_hit(event, rail_collision=False))
    if (
        not is_rail
        and event.property_damage_usd is not None
        and event.property_damage_usd >= PROPERTY_DAMAGE_THRESHOLD_USD
    ):
        hits.append(_property_damage_hit(event))
    if is_rail and event.serious_injury:
        hits.append(_rail_serious_injury_hit())
    if is_rail and event.substantial_damage:
        hits.append(_rail_substantial_damage_hit())
    if (
        is_rail
        and effective_category == "collision"
        and event.involves_second_rail_vehicle
    ):
        hits.append(_rail_to_rail_hit(addendum=False))
    if event.evacuation_life_safety:
        hits.append(
            ThresholdHit(
                threshold_id="evacuation_life_safety",
                plain_language=(
                    "People were evacuated for life-safety reasons."
                ),
                citation=(
                    f"p. 17 evacuation rule ({_TRACKER_POINTER}); verbatim "
                    f"quote was PENDING at 0.1.0 — see the S&S addendum"
                ),
            )
        )
    if is_rail and event.event_category == "derailment":
        hits.append(
            ThresholdHit(
                threshold_id="derailment",
                plain_language="A rail transit vehicle derailed.",
                citation=(
                    f"p. 17 derailment rule ({_TRACKER_POINTER}); verbatim "
                    f"quote was PENDING at 0.1.0 — see the S&S addendum"
                ),
            )
        )
    if event.event_category == "cyber" and event.substantial_damage:
        hits.append(_cyber_hit())

    basis: list[ThresholdHit] = []
    if event.injuries >= 1:
        basis.append(
            ThresholdHit(
                threshold_id="non_major_injury_event",
                plain_language=(
                    f"{event.injuries} person(s) were taken directly from "
                    f"the scene for medical care, without meeting a "
                    f"major-event threshold for this mode."
                ),
                citation=(
                    "p. 3 — S&S-50 scope: injury-threshold events "
                    f"({_TRACKER_POINTER})"
                ),
            )
        )
    basis.extend(_shared_non_major_basis(event, effective_category))

    notes: tuple[ThresholdHit, ...] = (
        (category_note,) if category_note is not None else ()
    )
    return _verdict(
        event, hits, basis, notes, effective_category, is_rail, "0.1.0"
    )


#: The ONLY INSERT path into safety.event_classifications (migration 0017's
#: only-writer rule): the API and any batch job call this, never their own
#: SQL. thresholds_met binds as a list (drivers adapt it to TEXT[]).
_INSERT_CLASSIFICATION_SQL = (
    "INSERT INTO safety.event_classifications "
    "(event_id, classification, thresholds_met, classifier_version) "
    "VALUES (%s, %s, %s, %s) "
    "RETURNING classification_id, classified_at"
)


def record_classification(conn, classification: SsClassification):
    """Persist one classification row; returns (classification_id,
    classified_at).

    Takes any DB-API 2.0 connection (%s placeholders — the persist.py
    precedent); transaction control stays with the caller so the event
    INSERT, this row, and the audit record commit (or abort) together.
    """
    cur = conn.cursor() if hasattr(conn, "cursor") else None
    version = f"{classification.calc_name} {classification.calc_version}"
    params = (
        classification.event_id,
        classification.classification,
        list(classification.thresholds_met),
        version,
    )
    if cur is not None:
        cur.execute(_INSERT_CLASSIFICATION_SQL, params)
        row = cur.fetchone()
    else:  # psycopg-style conn.execute (the API's connection shape)
        row = conn.execute(_INSERT_CLASSIFICATION_SQL, params).fetchone()
    if row is None:
        raise RuntimeError(
            "The classification insert returned no id; refusing to treat "
            "the event as classified."
        )
    return row[0], row[1]


def classification_to_dict(classification: SsClassification) -> dict:
    """JSON-safe dict of the verdict (the API response / audit detail shape)."""
    return {
        "event_id": classification.event_id,
        "classification": classification.classification,
        "thresholds_met": list(classification.thresholds_met),
        "explanations": [
            {
                "threshold": h.threshold_id,
                "plain_language": h.plain_language,
                "citation": h.citation,
            }
            for h in classification.threshold_hits
        ],
        "non_major_basis": [
            {
                "basis": h.threshold_id,
                "plain_language": h.plain_language,
                "citation": h.citation,
            }
            for h in classification.non_major_basis
        ],
        "effective_category": classification.effective_category,
        "is_rail_mode": classification.is_rail_mode,
        "summary": classification.summary(),
        "classifier_name": classification.calc_name,
        "classifier_version": classification.calc_version,
    }


def classification_to_json(classification: SsClassification) -> str:
    return json.dumps(classification_to_dict(classification), sort_keys=True)
