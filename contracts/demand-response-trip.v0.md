# Demand Response Trip — wire contract v0 (handoff 0013)

`demand_response_trip` is Headway's second data-source family: demand-response
(DR) / on-demand trips originate in **dispatch and scheduling platforms**
(Via, Spare, Ecolane, Trapeze), not in GTFS-RT. This contract is the
vendor-neutral record every DR connector produces; the schema is
[`demand-response-trip.v0.schema.json`](demand-response-trip.v0.schema.json).

Every regulatory statement below is a **pointer** to the quotes in
`services/calc/REGULATORY_TRACKER.md`, section *"Verified — Demand Response /
on-demand reporting (verified 2026-07-12)"* (2026 NTD Full Reporting Policy
Manual, printed pp. 33, 37–39, 129–139, 143–144). Verify against the current
published manual before extending — never from memory.

## Transport

- **Serialization:** CSV, one record per row, header row required, columns
  named exactly as the schema properties. Booleans are the literals
  `true`/`false` (case-insensitive); absent optional values are empty cells;
  timestamps are ISO 8601 **with a UTC offset** (a naive timestamp is
  quarantined downstream, never guessed); miles are plain decimal strings
  (exact NUMERIC end to end, never binary float).
- **File drop:** files matching `demand_response_trips*.csv` in the DR
  connector's drop directory (`DR_DROP_DIR`, `services/ingestion`).
- **Machine push:** `POST /ingest/dr/trips` with the CSV file as the raw
  request body, authenticated by a machine key holding the `ingest:dr` scope
  (handoff 0006 pattern).
- **Envelope:** either path stores the exact bytes content-addressed
  (`raw/dr/<sha256>.csv`) **before** producing a
  `raw-record-envelope.v0.schema.json` envelope to `raw.dr.trips`
  (`topics.v0.md`), keyed by `record_id`.
- **Source labeling (binding, the handoff-0005 rule applied to DR):** real
  dispatch feeds use envelope `source = "dr"` (or the vendor label bound to
  the pushing machine key); simulator output MUST use `source =
  "dr_simulated"` (file drop: `DR_SOURCE=dr_simulated`; push: a key bound to
  that source label). The source flows verbatim to
  `canonical.dr_trips.source`, so simulated data stays permanently
  distinguishable in provenance.

## Record semantics (what each field is for)

| Field | Why it exists (tracker quote it serves) |
| --- | --- |
| `dr_trip_id`, `service_date`, `vehicle_id` | One record per **booking**; vehicle-day accounting groups by `(vehicle_id, service_date)`. A shared ride is several bookings on one vehicle with overlapping onboard windows. |
| `mode` (`DR`), `tos` (`DO\|PT\|TX\|TN`) | Mode per the p. 33 DR definition; TOS per pp. 37–39. TOS changes the revenue rule: **TX** reports *"only the miles and hours when a transit passenger is onboard"* (p. 129); TX/TN report **no deadhead** (p. 130). |
| `request_timestamp`, `dispatch_timestamp` | Response-time analytics later; not consumed by v0 calcs. |
| `pickup_timestamp`, `dropoff_timestamp` | The revenue-time anchors: DR revenue time runs *"from the point of the first passenger pick-up to the last passenger drop-off"* (p. 129). For a **no-show**, pickup = arrival at the pickup point, dropoff = departure after the no-show was resolved (Exhibit 36: the no-show trip is actual AND revenue). |
| `pickup_lat/lon`, `dropoff_lat/lon` | Locations (optional); v0 calcs never derive distance from them (no guessed routing). |
| `onboard_miles`, `distance_source` | The measured **passenger-onboard segment distance** — the TX onboard-only miles source and the DR passenger-mile (PMT) input. Absent = unmeasured; downstream flags the gap. |
| `pickup_odometer_miles`, `dropoff_odometer_miles` | Odometer pairs make **empty inter-passenger travel** (revenue per Exhibit 36) and whole revenue spans exactly measurable; without them those legs are flagged unmeasured, never interpolated. |
| `riders`, `attendants_companions` | UPT: riders plus **non-employee** attendants/companions (pp. 143–144: they count *"as long as they are not employees of the transit agency"*). The employee rule is applied by the exporter — employees never enter this field. Both are 0 on a no-show (revenue time yes, boarding no). |
| `ada_related` | ADA complementary paratransit split: included in total UPT, **never** in the sponsored split (pp. 143–144). |
| `sponsored`, `sponsor` | Sponsored-service split (Medicaid, Meals-On-Wheels, …): included in total UPT (pp. 143–144). `sponsor` is required when `sponsored=true`. |
| `no_show` | Exhibit 36: *"Driver travels to pick up a passenger but the passenger is a no-show"* → actual + revenue — with **zero** boardings. |
| `interruption_after` | Breaks the vehicle-day revenue span per p. 129: garage return, dispatching-point return, lunch, fueling/servicing. Fueling and lunch travel are *neither revenue nor deadhead* (p. 130). |
| `driver_shift_id`, `dispatching_point_id` | References for the six p. 130 **deadhead leg types** (garage→dispatching point; garage→first pickup; dispatching point→first pickup; last dropoff→dispatching point; last dropoff→garage; dispatching point→garage). Trip records alone cannot *time* those legs; these references let a future shift-level feed measure them without a contract break. |

## Worked example — mapping a Via-style CSV export

No real Via Connect export sample is available yet (handoff 0013 open
question — a real-sample adapter is ROADMAP; **docs mandatory, adapter code
out of scope**). The mapping below is a worked example over an
**illustrative** Via-style ride export so an integrator can see the shape of
the work; column names are plausible, not authoritative.

Illustrative vendor row:

```csv
Ride ID,Service Day,Van ID,Rider Count,Extra Riders,Requested At,Assigned At,Pickup Arrival,Pickup Departure,Dropoff Arrival,Ride Distance (mi),Pickup Latitude,Pickup Longitude,Dropoff Latitude,Dropoff Longitude,Ride Type,Funding Source,No Show,Break After
R-88213,2026-07-14,VAN-07,1,1,2026-07-14T13:02:11Z,2026-07-14T13:04:40Z,2026-07-14T13:21:05Z,2026-07-14T13:23:30Z,2026-07-14T13:49:12Z,6.8,42.3601,-71.0589,42.3736,-71.1097,ADA,,false,lunch
```

Mapping to `demand_response_trip` v0:

| Vendor column | Contract field | Rule |
| --- | --- | --- |
| `Ride ID` | `dr_trip_id` | verbatim |
| `Service Day` | `service_date` | verbatim (ISO date) |
| `Van ID` | `vehicle_id` | verbatim |
| — | `mode` | constant `DR` |
| — | `tos` | from the agency's contract with the vendor, **not** from the export: a dedicated-vehicle turnkey contract is `PT`; agency-operated is `DO`; non-dedicated TNC dispatch is `TN`; non-dedicated taxi is `TX` (pp. 37–39 quoted in the tracker — note *"a taxi contract with dedicated transit-only vehicle time is PT, not TX"*) |
| `Requested At` | `request_timestamp` | verbatim |
| `Assigned At` | `dispatch_timestamp` | verbatim |
| `Pickup Departure` (boarded) | `pickup_timestamp` | boarding time; for a no-show use `Pickup Arrival` |
| `Dropoff Arrival` | `dropoff_timestamp` | alighting time; for a no-show use the pickup-point departure time |
| `Ride Distance (mi)` | `onboard_miles` | verbatim; `distance_source` = `gps` (Via-class platforms measure by GPS; odometer columns are typically absent → `pickup_odometer_miles`/`dropoff_odometer_miles` empty, and Headway flags empty inter-passenger travel as unmeasured rather than guessing) |
| `Rider Count` | `riders` | verbatim |
| `Extra Riders` | `attendants_companions` | ONLY after the agency confirms these are non-employee attendants/companions (pp. 143–144 employee rule); otherwise 0 |
| `Ride Type` = `ADA` | `ada_related` | `true`; else `false` |
| `Funding Source` non-empty | `sponsored` + `sponsor` | `true` + the label; empty → `false` |
| `No Show` | `no_show` | verbatim; the mapper must also zero `riders`/`attendants_companions` on no-shows |
| `Break After` | `interruption_after` | vendor break vocabulary → `none\|lunch\|fuel\|garage_return\|dispatch_return`; unknown values must FAIL the mapping (quarantine), never default silently |
| `Pickup/Dropoff Latitude/Longitude` | `pickup_lat/lon`, `dropoff_lat/lon` | verbatim |
| — | `driver_shift_id`, `dispatching_point_id` | empty until the vendor export carries shift/depot references |

Mapped contract row:

```csv
dr_trip_id,service_date,vehicle_id,mode,tos,request_timestamp,dispatch_timestamp,pickup_timestamp,dropoff_timestamp,pickup_lat,pickup_lon,dropoff_lat,dropoff_lon,onboard_miles,distance_source,pickup_odometer_miles,dropoff_odometer_miles,riders,attendants_companions,ada_related,sponsored,sponsor,no_show,interruption_after,driver_shift_id,dispatching_point_id
R-88213,2026-07-14,VAN-07,DR,PT,2026-07-14T13:02:11Z,2026-07-14T13:04:40Z,2026-07-14T13:23:30Z,2026-07-14T13:49:12Z,42.3601,-71.0589,42.3736,-71.1097,6.8,gps,,,1,1,true,false,,false,lunch,,
```

## Honest scope (documented guidance, never silent logic)

- **TX voucher programs:** *"Voucher Programs are not considered public
  transportation"* (pp. 37–39, quoted in the tracker). An agency mapping a
  voucher program onto `tos=TX` is out of scope for NTD reporting — this is
  an **intake validation concern**: confirm at onboarding that TX records
  are dispatched taxi service, not vouchers. Headway does not (and cannot)
  detect voucher programs from trip records.
- **Purchased transportation (PT):** the buyer reports only when the p. 38
  criteria hold (written agreement, full cost of service, buyer branding,
  seller obligated to supply NTD statistics; *"buyer reports, seller
  doesn't"*). Contract-level facts — documented guidance for the agency, not
  record-level logic.
- **Shared-vehicle multi-agency rule (p. 131):** two agencies' passengers on
  one DR vehicle at the same time → *"the agency operating the service must
  report it"*; no splitting. Each Headway database is one agency (ADR-0004);
  do not feed another agency's operated service into this contract.
- **Deadhead measurement:** trip records carry deadhead *references* only;
  the six p. 130 leg types are classified (and Exhibit 36 rows golden-pinned)
  in `services/calc/headway_calc/dr.py`, but leg durations/distances are not
  measurable from this contract. TX/TN report no deadhead at all (p. 130).
- **Scheduled service:** *"Full Reporters do not report scheduled service for
  the TX and TN TOS"* (p. 139) — reporting-surface guidance, no field here.
