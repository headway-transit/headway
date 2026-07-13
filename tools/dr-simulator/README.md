# Demand-response dispatch-day simulator

Generates **SIMULATED** — but contract-valid — `demand_response_trips.csv`
files per the `demand_response_trip` v0 wire contract
(`contracts/demand-response-trip.v0.schema.json` +
`contracts/demand-response-trip.v0.md`, handoff 0013): multi-vehicle
dispatch days with shared rides, no-shows, lunch/fuel interruptions,
garage/dispatching-point returns, ADA-related and sponsored splits, and
odometer readings. It exists because no public booking-level DR dispatch
dataset is available, and the DR calcs + intake path need realistic
dispatch days.

## The output is SIMULATED data (binding provenance rule)

Simulated DR records must enter Headway with envelope
**`source = "dr_simulated"`** — never `"dr"` (the handoff-0005 binding rule,
applied to DR by handoff 0013):

- **File drop:** put the output in the DR connector's `DR_DROP_DIR` with
  **`DR_SOURCE=dr_simulated`** (`services/ingestion`).
- **Machine push:** `POST /ingest/dr/trips` with a machine key **bound to
  source label `dr_simulated`** (the endpoint stamps the key's bound label;
  a client-supplied source is ignored).

The source flows to `canonical.dr_trips.source`, and every DR calc consuming
simulated records surfaces it (`simulated_source_data` info finding) — a
certifiable figure silently containing simulated records is exactly the
contradiction the DQ trail exists to expose.

Since the 2026-07-13 hardening pass this rule is ENFORCED, not
conventional: every generated `dr_trip_id` carries the structural `sim:`
prefix (a pinned regression test keeps it there), the DR connector has NO
default source label (`DR_SOURCE` is required; it refuses to start
without one), and a file whose rows carry the `sim:` marker arriving
under a non-`*_simulated` source label is hard-refused — moved to the
drop dir's `rejected/`, loudly logged, never landed (Shared Constraint 2:
full provenance).

## Usage

```
python3 simulate.py --service-date 2026-07-14 --seed 42 --out /path/to/dropdir
```

No database is needed: DR trips originate in dispatch platforms, so the
simulator is self-contained (unlike `tools/tides-simulator`, which aligns
with operated GTFS trips).

Options:

| Flag | Meaning |
| --- | --- |
| `--tos-mix DO:3,PT:2,TX:1` | vehicles per type of service (default shown). TX vehicles are non-dedicated: sequential bookings, no interruption markers. |
| `--trips-per-vehicle 8` | mean bookings per vehicle-day (±2 jitter) |
| `--seed 0` | deterministic RNG seed — same arguments + seed give byte-identical output |

Determinism: all randomness flows through one `random.Random(seed)`.
(Seeded randomness is fine here: this is a simulator, not calc code.)

## Defect injection

Each flag is a fraction in `[0, 1]`, default `0`. Defect sets are disjoint
and deterministically assigned from the seed. They exercise the fail-loudly
paths downstream:

| Flag | Injected defect | Exercises |
| --- | --- | --- |
| `--missing-distance-share` | completed trips with **no** onboard_miles and **no** odometer readings | dr_vrm / dr_pmt unmeasured-distance warnings (a distance is never guessed) |
| `--negative-duration-share` | dropoff before pickup | transform malformed-row quarantine |
| `--ada-sponsored-conflict-share` | trips flagged BOTH ada_related and sponsored | dr_upt conflict warning (ADA-related UPT is never sponsored — manual pp. 143–144 as quoted in the tracker) |
| `--missing-sponsor-share` | sponsored=true with no sponsor label | transform malformed-row quarantine |

## Output

`<out>/demand_response_trips.csv` with the full contract column list —
matching the DR connector's `demand_response_trips*.csv` file pattern.
