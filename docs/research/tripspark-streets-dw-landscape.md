# What lives in a TripSpark Streets data warehouse — an inventory, ranked for NTD work

*2026-07-31. Source: a full table inventory (name + row count) of the Streets
reporting warehouse at a partner agency running fixed-route service with roughly
160 vehicles. The agency is deliberately not named; the raw inventory is not
committed. Row counts are rounded. Column-level knowledge comes from the same
agency samples that produced `adapters/tripspark/streets/` — derived observations,
not vendor documentation.*

TripSpark Streets is a CAD/AVL + APC product; its "storage server" warehouse is
what the vendor's own reports read. For an agency asking "can Headway use what we
already have?", this is the landscape. 128 tables fall into eight families.

## The families, ranked by NTD value

### 1. APC — the ridership evidence (`VehicleLocationAPC`, ~84M rows)
One row per stop event with boarding/alighting counts, stop identity, trip/block/
route references, and an `APCSource` discriminator. This is the table Headway's
adapter already ingests (`adapters/tripspark/streets/mapping.v0.yaml`) — the
source of UPT. Two companions raise the ceiling:

- **`VehicleLocationTPBalanced` (~25M) + `APCBalancingLog` (~209k)** — the
  vendor's own count-balancing pipeline: raw counts adjusted so ons equal offs.
  Headway deliberately ingests the *raw* counts and applies its own validations
  (the FTA imbalance rule is quoted in `upt_v0`); the balanced tables are a
  cross-check target, and the balancing log is exactly the kind of adjustment
  record an APC benchmarking exercise wants (the FTA benchmarking checklist is
  already on the ROADMAP).
- **`VehicleLocationAPCFreeWork`, `VehicleLocationAPCSpecialEvent`** — near-empty
  here, but their existence documents how the product classes non-revenue and
  special-event work; relevant when quoting what counts toward revenue service.

### 2. Schedule adherence — a second opinion on OTP (`EventScheduleAdherence` ~3.5M, `…Log` ~7.2M)
The vendor computes schedule adherence events continuously. Headway computes OTP
from raw positions under quoted TCQSM definitions (`otp_v0`). Holding both means
an agency can *reconcile* the two — and when they disagree, the receipts decide.
`EventRouteAdherence(Log)` does the same for route deviation. The `Event*` /
`Event*Log` pairing runs through the whole product: the un-suffixed table is the
current/summarized event, the `Log` is the history.

### 3. The schedule mirror (`sch_*`, ~30 tables)
The vendor-side schedule: `sch_Trip` (~560k), `sch_TripPoint` (~18M),
`sch_PatternPoint` (~6.8M), `sch_Stop` (~180k), `sch_Block` (~21k),
`sch_Route` (~3.7k), `sch_Direction` (10 rows), calendars, patterns. Three uses:

- **Trip resolution.** Headway's per-agency resolution config (handoff 0031)
  joins the export's trip naming to published GTFS. Where GTFS is thin, the
  schedule mirror is the fallback source of truth for what was *scheduled*.
- **Block vocabulary.** `sch_Block`/`sch_BlockItem` carry the operational block
  names an ops room actually uses — the same names handoff 0038 attaches to
  findings so a dispatcher reads "block 3-2", not a UUID.
- **Direction decoding.** `sch_Direction` is 10 rows — the names behind the
  export's `DirectionKey`. Small tables like this one settle mapping questions
  that would otherwise be guessed; Headway refuses to guess them (the
  resolution config ships `confirmed: false` until the agency confirms).

### 4. Raw AVL — the deep telemetry archive (`VehicleLocation`, ~774M rows)
Every breadcrumb, apparently for the warehouse's whole life (~7,900 rows in
`DateDimension` ≈ two decades of calendar). Alongside: `VehicleLocationTP`
(~113M, trip-aligned), `VehicleLocationInpt` (~33M), `VehicleLocationOBD`
(~1.3M, engine bus data), fare-tagged variants (~13M). Headway's VRM/VRH come
from its own GTFS-RT capture; this archive matters for two reasons: it reaches
*back* before Headway existed (historical baselines, telemetry-gap backfill
questions), and its sheer size is a caution for anyone writing a `SELECT *`
export — the view-is-the-contract pattern (handoff 0033) exists precisely so an
agency never ships 774M rows to prove a month.

### 5. Workforce and operations (`sch_Work*`, `sch_Run*`, `sch_Roster*`, `VehicleLogon` ~305k, `Employee` 535)
Runs, rosters, work items, logons, dispatch text messages (~590k rows across the
`TextMessage*` tables). **This family is employee-adjacent by construction**
(see `docs/data-classification.md`): a logon row places a person on a vehicle;
rosters place them on a shift. Headway does not ingest any of it today, and any
future use goes through the aggregate-by-default / purpose-bound-access pattern
that document records. It is listed here because an inventory that omitted it
would misstate what the warehouse holds.

### 6. Safety-relevant events (`EventSilentAlarm` ~330 + log, `EventGeofenceSpeeding` ~3.8M + log)
Silent alarms are candidate S&S-module inputs (the S&S event vocabulary is
quoted in `services/calc/REGULATORY_TRACKER.md`). Speeding events are both a
safety signal and a discipline-sensitive employee record — same handling rule as
family 5. Geofence machinery (`GeoFence`, 13 zones) shows what the agency
actually fences: yards and hot spots.

### 7. Vehicle condition (`VehicleCheckResponse` ~1.4M, `VehicleCheckCompleted` ~84k, `VehiclePullout` ~181k)
Pre-trip inspection responses and pullout records — an operations/maintenance
story (and a VOMS cross-check: what pulled out versus what the telemetry saw in
service). Not connected today; honest roadmap material.

### 8. The empty tables — capability the product has, the deployment doesn't use
Forty-plus tables sit at zero rows, and the zeros are informative:

- `EventPassengerVolume(Log)` — the product can event-ize passenger loads;
  unused here (APC rides on the location stream instead).
- `EventWheelchair(Log)` — zero. Accessibility boardings are not evented in
  this deployment; anyone promising wheelchair-boarding stats from this
  warehouse would be promising data that does not exist.
- `EventDTC`/`DiagnosticTroubleCode`, idling/harsh-driving/acceleration events —
  the telematics-style capabilities are dormant (the agency's vanpool telematics
  live in a different vendor entirely).
- `EventTransfer(Log)` — no transfer eventing; linked-trip analysis would need
  fare data, not this warehouse.

## Two operational footnotes worth more than they look

- **`DeleteProcessLog` (158 rows) and `ETLProcessLog` (~130)** — the warehouse
  runs a delete process. That is a retention policy executing, whether or not it
  is written down anywhere. ADR-0012's position — retention is a records policy,
  and the auditor asks for it — applies to the *vendor* store too: if the DW
  purges history on a schedule the agency has not chosen deliberately, the
  agency's Headway capture may end up the more durable record.
- **`Agency` (1 row)** — the schema is multi-tenant-shaped but single-tenant
  deployed. Vendor-generic adapters should not assume the agency key is
  meaningful.

## What this means for a connecting agency

1. The APC table you already have is enough for UPT with receipts — one
   read-only view (`docs/connecting-your-data.md`), no new hardware.
2. Adherence, block names, and the direction table each cost one small export
   and each buys plain-language findings or a cross-check on a reported figure.
3. The workforce and discipline-adjacent tables should stay out of scope until
   the governance work (classification, purpose-binding) says otherwise — the
   platform is deliberately built so leaving them out loses nothing certifiable.
4. Ask your vendor what the delete process's schedule is. The answer belongs in
   your records-retention policy either way.
