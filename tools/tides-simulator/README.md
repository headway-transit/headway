# TIDES passenger_events simulator

Generates **SIMULATED** — but TIDES-spec-valid — `passenger_events.csv`
files for the trips actually operated on a service date, read from
`canonical.trips` + `canonical.vehicle_positions`. It exists because no
public event-level APC dataset is available (the TIDES `/samples` directory
is template-only; handoff 0005), and slice 2's UPT calc needs event-level
boardings aligned with real operations.

Schema verified against TIDES-transit/TIDES `spec/passenger_events.schema.json`
(commit `d887d42ce081f3fb6155664a3c486101d62ec52b`, fetched 2026-07-10) —
re-verify the field list and `event_type` enumeration against the current
spec before extending; never extend from memory.

## The output is SIMULATED data (binding provenance rule)

Drop the output into the ingestion connector's `TIDES_DROP_DIR` with
**`TIDES_SOURCE=tides_simulated`** — never `tides`. The envelope `source`
flows to `canonical.passenger_events.source`, and any calc consuming
simulated records must surface it (`simulated_source_data` info finding);
a certifiable figure silently containing simulated records is exactly the
contradiction the DQ trail exists to expose (handoff 0005 binding rule).

## Usage

```
python3 simulate.py --service-date 2026-07-08 --seed 42 --out /path/to/dropdir
```

Connection comes from the environment, same rules as `db/migrate.py`:
`DATABASE_URL` if set (percent-encode credentials), otherwise libpq-style
`PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDATABASE`. Requires
`psycopg` (v3). The core logic takes an injected DB-API connection; tests
run against a fake, no live DB.

Determinism: all randomness flows through one `random.Random(seed)` — same
inputs + same `--seed` give byte-identical output. (Seeded randomness is
fine here: this is a simulator, not calc code.)

## Defect injection

Each flag is a fraction in `[0, 1]`, default `0`. The defects exist to
exercise the FTA validation rules quoted in handoff 0005 (2026 NTD Policy
Manual):

| Flag | Injected defect | Exercises |
| --- | --- | --- |
| `--missing-trip-share` | That share of operated trips generates **no** events | p. 146 missing-trip rule: factor up at ≤ 2% missing, statistician approval above |
| `--imbalance-share` | Trips whose alightings differ from boardings by **more than 10%** | p. 151 boarding/alighting imbalance flag |
| `--negative-load-share` | Trips with an early alighting exceeding prior boardings (running load < 0) | p. 151 negative-load flag |

Defect sets are disjoint and deterministically assigned from the seed.

## Output

`<out>/passenger_events.csv` with columns
`passenger_event_id, service_date, event_timestamp, trip_id_performed,
trip_stop_sequence, event_type, vehicle_id, event_count` (all six required
TIDES fields plus the optional ones the simulator populates). Only
`Passenger boarded` / `Passenger alighted` event types are emitted (both
members of the verified enum).

## Tests

```
python3 -m pytest tests/ -q
```
