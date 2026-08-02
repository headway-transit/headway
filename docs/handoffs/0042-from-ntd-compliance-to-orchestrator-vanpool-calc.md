# Handoff: NTD/Compliance Engineer → Orchestrator — Vanpool (VP mode) calc over fleet telematics

## Context

Handoff 0028 landed the Samsara fleet-telematics connector and deliberately
computed ZERO figures, gating VP-mode numbers on "the FTA vanpool rules quoted
verbatim into `services/calc/REGULATORY_TRACKER.md` by the NTD Compliance
role, plus an agency-declared way of saying which vehicle-days were revenue
service." This handoff delivers that compliance gate: the vanpool rules quoted
verbatim, and a VP calc over the fleet-telematics contract that computes what
telematics can honestly support and REFUSES — naming what is missing — for
what it cannot. It lights up the "Rideshare" (VP) mode view.

The load-bearing finding: **fleet telematics (measured vehicle movement)
cannot supply any certifiable VP figure.** The FTA manual's own model of
vanpool VRM/VRH is rider-self-reported per trip (p. 131), 100%-count with no
estimation allowed (p. 122); the vanpool van is defined by only "80 percent of
the yearly mileage comes from commuting" (p. 36); UPT counts boardings and the
driver-as-passenger rule turns on the driver's employment status (p. 143);
VOMS is a revenue-service simultaneity count (Exhibit 38, p. 138). Telematics
carries none of that — it measures distance (all movement) and engine time. So
every VP figure REFUSES, honestly, rather than substituting all-movement for
revenue service.

## Inputs (what was given)

- **Contract:** `contracts/fleet-telematics.v0.schema.json` + `.md` (the
  honesty wall), landed as `canonical.vehicle_telematics_days` (migration
  0034). One row per (vehicle, service date, measure, basis, source record).
- **Manuals:** 2026 + 2025 NTD Full Reporting Policy Manuals
  (`docs/reference/`), public domain, on file.
- **Prior art:** the DR calcs (`headway_calc/dr.py`) as the mode-scoped
  refuse-or-compute pattern; `REGULATORY_TRACKER.md` as the quote-or-own-it
  discipline.

## Outputs (what was produced)

### The vanpool rules quoted verbatim (page cites)

All in `REGULATORY_TRACKER.md` → "Verified — Vanpool (VP mode) reporting
(verified 2026-07-31)". Re-read against the 2026 PDF; the 2025 manual carries
identical text (spot-verified per page). Key quotes:

- **VP mode definition, incl. the 80%-commuting clause** — p. 36.
- **VRM/VRH = "miles/hours vehicles travel while in revenue service" and
  "exclude ... Other non-revenue uses of the vehicles"** — p. 128.
- **"agencies must collect and record 100 percent of all miles and hours ...
  FTA does not allow agencies to estimate these data"** — p. 122.
- **VP VRM/VRH rider-self-reported: "passengers fail to report data for VRM
  and VRH ... contact the assigned NTD analyst"** — p. 131 (the pivotal
  VP-specific rule).
- **VP driver-as-passenger UPT rule** — p. 143.
- **VP/DR VOMS = "largest number of vehicles in revenue service at any one
  time ... (includes atypical service)"** — Exhibit 38, p. 138.
- **VP days-operated exception ("only ... when service was provided")** — p.
  155; **seating capacity treats the VP driver as a passenger** — p. 202.

### The calc — `headway_calc/vp.py` (calcs vp_vrm_v0 / vp_vrh_v0 / vp_upt_v0 / vp_voms_v0, all 0.1.0)

Four pure functions over `VpTelematicsDay` (the canonical
`vehicle_telematics_days` read type, new in `types.py`). **Every figure
REFUSES** (value None; one blocking finding naming the missing input;
`input_record_ids` empty — records cited by findings):

| calc | refusal finding | missing input |
| --- | --- | --- |
| `compute_vp_vrm` | `vp_vrm_needs_revenue_service_declaration` | agency-declared revenue-commuting portion of each vehicle-day |
| `compute_vp_vrh` | `vp_vrh_needs_revenue_service_declaration` | same (engine time ≠ revenue hours) |
| `compute_vp_upt` | `vp_upt_needs_passenger_roster` | passenger boarding counts + driver employment/purpose status |
| `compute_vp_voms` | `vp_voms_needs_revenue_service_declaration` | revenue-service declaration (for simultaneity) |

**What it DOES deliver (context, never a reportable figure):** each result
carries a `VpTelematicsDetail` recording the observed movement per basis
(distance meters / engine seconds actually measured), bases kept distinct,
unmeasured series stated (never zeroed), plus:

- `vp_telematics_basis_conflict` (warning) — two distance bases on a
  vehicle-day disagreeing beyond `basis_conflict_tolerance_meters` (default
  100 m — engineering placeholder, explicit input): Shared Constraint 7,
  surfaced never averaged.
- `vp_telematics_series_unmeasured` (warning) — a value-absent series (fewer
  than two readings / counter regression).
- `simulated_source_data` (info) — any non-`samsara` source label (e.g.
  `samsara_simulated`): a certifiable figure over simulated data is a
  contradiction, recorded independently of the refusal.

Persist mapping added (`persist.py`): `vp_vrm_v0`→`vrm`, `vp_vrh_v0`→`vrh`,
`vp_upt_v0`→`upt`, `vp_voms_v0`→`voms`, intended for **scope `mode:VP`** (the
DR scope pattern). In v0 nothing persists — `persist_result` refuses value
None (verified by test).

### Runner wiring — DEFERRED to the orchestrator (conflict avoidance)

`runner.py` and `REGULATORY_TRACKER.md` are being changed concurrently by wave
0040; the calc + tests are therefore standalone and the runner wiring is NOT
done here. Wiring is genuinely a follow-up regardless: **there is no
`load_vehicle_telematics_days` reader yet** (`reader.py` has loaders for
positions, events, dr_trips, etc. but not telematics), so wiring VP into
`run_period` needs that loader first. The one-line-per-figure wiring, once a
loader exists, mirrors the DR block (`runner.py` ~line 708):

```python
# after: telematics = load_vehicle_telematics_days(conn, period_start, period_end)
if telematics:
    for result in (compute_vp_vrm(telematics), compute_vp_vrh(telematics),
                   compute_vp_upt(telematics), compute_vp_voms(telematics)):
        scoped_results.append(("mode:VP", result))
```

Because all four refuse (value None), the runner's existing fail-loudly-first
path routes their blocking findings to `dq.issues` and never reaches
`persist_result` — no VP `metric_values` row is written until a reportable
version exists. (A `SCOPE_MODE_VP = "mode:VP"` constant alongside
`SCOPE_MODE_DR` is the clean form.)

## Open Questions

1. **The revenue-service declaration surface (owner: NTD role + Platform /
   Data Engineer).** VRM/VRH/VOMS need an agency-declared statement of which
   vehicle-days (and which portion of each) were revenue commuting service.
   Proposed default: an audited `app.*` overrides-style surface (the
   `service_day_overrides` precedent), NOT a telematics field. Until it
   exists, VP VRM/VRH/VOMS stay refused.
2. **VP UPT roster input (owner: Ingestion + NTD role).** UPT needs boarding
   counts and driver employment/purpose — a roster / ride feed, out of scope
   for the telematics connector (handoff 0028 deliberately does not ingest
   driver-identified data). Proposed default: a separate VP ridership feed.
3. **`basis_conflict_tolerance_meters` = 100 m** is an engineering
   placeholder. Proposed default: keep 100 m until observed inter-basis
   distributions inform a per-agency value.

## Verification Evidence

Commit context: worktree `agent-a3f272a90c3e30d6a`, branch `main` (no commits
— orchestrator integrates).

- **Verbatim quotes** cross-checked against
  `docs/reference/National Transit Database 2026 Policy Manual_ Full Reporting.pdf`
  via `pdftotext -layout` (pp. 36, 122, 128, 131, 138, 143, 155, 202) and the
  2025 manual confirmed identical at each page.
- **Full calc suite:** `cd services/calc && /home/daniel/venv/bin/python -m
  pytest -q` → **645 passed** (20.16s) after the change (was 605 before the 40
  new VP tests).
- **VP tests specifically:** `pytest -q tests/test_vp.py tests/test_golden_vp.py`
  → 40 passed. Covers: every figure refuses with value None + the naming
  finding; empty-input refusal (no silent zero); observed-movement context;
  unmeasured-series stated-not-zeroed; basis-conflict surfaced-not-averaged +
  tolerance as explicit input; simulated-source rule; persist refuses a
  refused result; input-contract guards (basis cannot cross its measure; naive
  window rejected).
- **Golden:** `tests/golden/vp_v0/{fixture,expected}.json` + `BASIS.md` — a
  two-van simulated day pinning the refusal contract and the observed movement
  (144900 m distance = 72000 + 72900; 43200 s engine; 1 basis conflict; 1
  unmeasured series).
- **Guardrails intact:** `test_purity.py` (vp.py imports stdlib +
  headway_calc.types only — no network/clock/randomness), `test_registry.py`
  (vrm/vrh/upt/voms already sign-neutral), `test_persist.py` all pass.

### Files changed

- `services/calc/headway_calc/vp.py` — NEW (the four VP calcs).
- `services/calc/headway_calc/types.py` — ADDED `VpTelematicsDay` (input),
  `VpTelematicsDetail` (detail) + basis/measure vocab constants; wired
  `VpTelematicsDetail` into the `CalcResult.detail` union.
- `services/calc/headway_calc/persist.py` — ADDED four `vp_*_v0` → metric
  entries to `_METRIC_BY_CALC_NAME` (additive).
- `services/calc/headway_calc/__init__.py` — exported the four `compute_vp_*`.
- `services/calc/REGULATORY_TRACKER.md` — APPENDED four calc rows + the new
  "Verified — Vanpool (VP mode) reporting" section (existing rows untouched).
- `services/calc/tests/test_vp.py`, `tests/test_golden_vp.py` — NEW.
- `tests/golden/vp_v0/{fixture.json,expected.json,BASIS.md}` — NEW.
- `docs/handoffs/0042-...md` — this file.

NOT touched: `upt.py`, `runner.py`, existing tracker rows (conflict avoidance
with wave 0040).

---

## External adversarial review — F3 fixed (2026-08-01)

A review by a different model family found `_observed_movement` inflating the
context detail that travels with every VP refusal. Two distinct breaks, both
real, both fixed:

1. **Bases were merged into a headline total.** A vehicle-day may report
   distance on both `ecu_odometer` and `gps_distance` — two measurements of the
   SAME movement. They were added, so the golden fixture asserted
   `observed_distance_meters = 72000 + 72900 = 144900` for a van that drove
   about 72 km. Picking one basis instead would be silent basis substitution,
   which ADR-0013 makes unrepresentable, so the honest answer is that **there
   is no single number**: when more than one basis measures a quantity the
   total is `None`, stated as undefined, and the per-basis breakdown carries
   the truth. The existing basis-conflict warning already names the
   disagreement (Shared Constraint 7 — surfaced, never averaged).
2. **Units were mixed.** `by_basis` was keyed by basis alone, so a source
   reporting distance AND engine time on one basis added **metres to seconds**
   in a single bucket. It is now keyed `measure:basis`.

Also corrected alongside: `vehicle_days_seen` / `vehicle_days_unmeasured`
counted **series**, not vehicle-days — one van on one date reporting two
distance bases plus engine time counted as 3 or 4 "vehicle-days". They now
count distinct `(vehicle_id, service_date)` pairs, so the fleet an auditor is
told was observed is the fleet that was observed.

**No reported figure changes** — every VP figure still REFUSES, by design; this
is the context block inside the refusal, which an auditor reads to understand
what was seen. A refusal that overstates the evidence behind it is still a
false statement, which is why this was worth fixing rather than filing.

The golden fixture had encoded the bug as intent (its own comment read
"observed_distance_meters = 72000 + 72900 = 144900"); both the fixture and its
comment are corrected, and the disagreeing-bases test now pins that the sum is
**not** reported. calc suite **681** green.
