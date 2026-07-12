/**
 * The /safety UI's map from the sscls_v0 classifier's machine tokens to the
 * VERIFIED manual quotes in quotes.json (handoff 0010). Each snippet locates
 * one quote via quoteContaining(); src/test/quotes.test.ts fails the suite
 * if any snippet here stops resolving — the receipts must never ship
 * without their rules.
 */

/**
 * Classifier token (threshold_id / non-major basis_id in
 * services/calc/headway_calc/sscls.py) → a snippet of its verbatim quote.
 * Tokens with no QUOTED rule in the tracker (today only non_major_fire —
 * the p. 3 "non-major fires" scope line is a tracker summary, not a
 * quotation — and the Scenario E category note) are deliberately absent:
 * the receipt states that gap out loud instead of paraphrasing a rule from
 * memory.
 */
export const THRESHOLD_QUOTE_SNIPPETS: Record<string, string> = {
  fatality: "Confirmed within 30 days, and include suicides.",
  injury_immediate_transport: "Immediate transport away from the scene",
  injury_two_or_more: "result in two or more injured persons",
  property_damage_25k: "equal to or exceeding $25,000.",
  rail_serious_injury:
    "Requires hospitalization for more than 48 hours within 7 days",
  rail_substantial_damage:
    "Disrupts the operations of the rail transit agency",
  cyber_substantial_damage: "is reportable as a Cyber Security Major Event.",
  rail_to_rail_collision:
    "Involve a rail transit vehicle and a second rail transit vehicle",
  rail_collision_grade_crossing:
    "Occur at a rail grade crossing or intersection",
  rail_collision_vehicle_contact_assault:
    "and assaults or homicides that involve contact with a transit vehicle",
  collision_towaway:
    "the towing away of any vehicles (transit or non-transit) from the scene",
  evacuation_life_safety:
    "Evacuation of a transit facility or vehicle for life-safety reasons.",
  rail_evacuation_to_row: "Evacuations to controlled rail right-of-way",
  derailment:
    "Both mainline and yard derailments and non-revenue vehicle derailments.",
  runaway_train: "uncommanded, uncontrolled, or unmanned",
  non_major_assault_on_worker:
    "Assaults on a transit worker do not require an injury",
  non_major_injury_event:
    "You must report each person transported away from the scene for medical attention as an injury",
  other_safety_event_single_injury:
    "are reported on the Non-Major Summary Report",
};

/** The S&S-40 30-day rule (Exhibit 2, p. 4). */
export const SS40_QUOTE_SNIPPET = "30 days after the date of the event";

/** The S&S-50 zero-event trap (p. 4 + Exhibit 3, p. 5). */
export const SS50_QUOTE_SNIPPET = "even if no event occurs";
