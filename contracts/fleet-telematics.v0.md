# Fleet Telematics Vehicle-Day — wire contract v0 (handoff 0028)

`fleet_telematics_vehicle_day` is Headway's third data-source family. Fixed
route arrives as GTFS/GTFS-RT; demand response arrives as dispatch-platform
trip records; **fleet telematics** arrives as a *sensor* API — odometers,
GPS distance counters, engine-hour meters read off a gateway bolted into the
vehicle. The first partner agency runs its vanpool on one of these systems,
and vanpool figures there are assembled by hand from odometer sheets today.

This contract is the vendor-neutral record every telematics connector
produces; the machine-readable form is
[`fleet-telematics.v0.schema.json`](fleet-telematics.v0.schema.json).

---

## THE HONESTY WALL — read this before the fields

**Telematics distance is not revenue miles. Engine and duty time are not
revenue hours.**

An odometer delta is everything the vehicle did: revenue service, deadhead
to and from the garage, the driver's lunch run, the trip to the tyre shop,
and — on a vanpool van that lives at a participant's house — personal use.
An engine-hour meter counts the engine running, including idling in a
parking lot. A driver's hours-of-service duty status is a *driver's*
regulated status, not a vehicle's revenue time.

Therefore, in this wave:

- Headway lands **raw + canonical telematics records only**. There is **no
  calculation**: no VRM, no VRH, no VP-mode figures, no "estimated revenue
  miles". Nothing in `services/calc/` reads these rows.
- Every canonical row carries **its measurement basis** and **its gaps**.
  Nothing is interpolated across a missing sample, and no basis is ever
  silently substituted for another.
- Turning any of this into a reportable vanpool figure requires the FTA
  vanpool rules **quoted verbatim** into `services/calc/REGULATORY_TRACKER.md`
  by the NTD Compliance role (the 2025/2026 manuals are on file in
  `docs/reference/`), plus an agency-declared way of saying which
  vehicle-days were revenue service. That is a **separate, compliance-gated
  wave**, recorded in handoff 0028's Open Questions.

What we ingest today is **measured vehicle movement**. It is not a number
anyone can put on a federal form, and Headway does not pretend otherwise.

---

## The record shape: one measure, one basis, one vehicle-day

A record is **one measurement series**: one vehicle, one service date, one
`measure` (`distance` | `engine_time`), on one `basis`. A vanpool van with
both an ECU odometer and a GPS distance counter produces **two** distance
records for the same day, not one reconciled number. That is deliberate:

- **Substitution becomes structurally impossible.** You cannot silently fill
  a missing ECU odometer with a GPS figure, because they are different rows
  with different `basis` values.
- **Disagreement stays visible.** Two bases that disagree by 41 miles is
  exactly the conflict Shared Constraint 7 says must surface, not be
  averaged away.
- **A new vendor basis is a new enum value**, not a schema rewrite.

### Fields

| Field | Why it exists |
| --- | --- |
| `vehicle_id`, `vehicle_label` | The source system's own identifier, verbatim. Headway never re-keys a vendor id. Matching a telematics vehicle to the agency's fleet roster is a separate, human-confirmed step — a gateway serial is not an asset number. |
| `service_date`, `window_start`, `window_end` | The service day, as the local wall date in the operator's **declared** service-day timezone, plus the explicit offset-bearing boundaries that define it. The zone is declared, never guessed; a deployment without one produces **zero** telematics rows (fail closed). The window is whatever the zone says — 23 or 25 hours across a DST change, never assumed to be 24. |
| `measure` | `distance` (how far the vehicle moved — ALL of it) or `engine_time` (how long the engine ran). Named for what was measured, never for what someone hopes to report. |
| `basis` | **How** it was measured. Distance: `ecu_odometer` (the vehicle's own number, off the diagnostic bus), `gps_odometer` (an odometer maintained from GPS travel and seeded by a human-entered reading — only ever as good as its seed), `gps_distance` (distance accumulated by the *gateway* since it was installed — it belongs to the gateway, not the vehicle, and it resets when the gateway is swapped). Engine time: `ecu_engine_time`, `estimated_engine_time` (an estimate, labelled as one, never promoted), `duty_status_time` (a driver's ELD/HOS duty time — a different subject entirely, carried here only so a future feed has somewhere honest to land). |
| `unit` | `meters` or `seconds`. SI on the wire, always. Miles and hours are a downstream, exact-decimal conversion — never done here, never in binary floating point. |
| `reading_kind` | `cumulative_counter` (the source reports a running total; `value` is last − first and **both endpoints are carried** so the subtraction is auditable and reversible) or `period_total` (the source already attributes an amount to a period; `value` is that amount as given). Both shapes exist across vendors. Neither is converted into the other. |
| `value` | The measured amount over the window. **Absent means UNMEASURED** — never 0, never interpolated, never extrapolated to the window boundaries. For a cumulative counter it covers only the span between the first and last reading actually received: movement before the first reading or after the last is not included and is not estimated. |
| `first_reading_at`/`first_reading_value`, `last_reading_at`/`last_reading_value` | The two readings the subtraction used, with their times. This is what makes `value` checkable by a human with the vendor's own dashboard open. Note what they are *not*: the start and end of the day. |
| `sample_count` | How many readings of this basis landed in the window. `0` or `1` still produces a record — the absence is stated, not left to be inferred from a missing row. |
| `max_sample_gap_seconds` | The record's honesty field: the largest interval between consecutive readings, i.e. how blind the measurement is between its endpoints. Absent when `sample_count < 2`. Headway never interpolates across a gap; a consumer must decide what a gap means and say so. |
| `source_system` | The **registered** source label (`samsara`, `samsara_simulated`). Real accounts use the plain label; anything synthetic MUST carry `_simulated`, so simulated data stays permanently distinguishable in provenance (handoff 0005 rule, handoff 0015 fail-closed enforcement). An unregistered label is refused fail-closed: raw record retained, blocking DQ issue, **zero** canonical writes. |

Adding a vendor means adding its labels to the `source_system` enum in the
schema — a contracts change under Platform Architect governance, never a
connector's private decision.

## Transport

- **Serialization on the wire:** the raw record is **the vendor's own
  response bytes, reduced to the data-minimization allow-list** (see below)
  and otherwise unmodified. Headway does not define a telematics file format
  — a telematics source is an API, and the immutable raw record is what the
  API returned minus the fields Headway must not collect. The fields above
  describe the **canonical** record the transform derives from those bytes;
  they are not a wire format a connector emits.
- **Topic:** `raw.telematics.vehicle_stats` (`topics.v0.md`), envelope
  `raw-record-envelope.v0.schema.json`, keyed by `record_id`.
- **Envelope:** `payload_encoding: object_ref` — one API response page's
  minimized bytes landed content-addressed at `raw/telematics/<sha256>.json`
  **before** the envelope is produced (minimize, then store, then produce).
  Same response → same minimized bytes → same `record_id` → idempotent
  re-poll.
- **Canonical landing:** `canonical.vehicle_telematics_days` (migration
  0034), one row per `(vehicle_id, service_date, measure, basis,
  source_record_id)`, each with a lineage edge back to the raw record and a
  DQ issue for every honest failure mode below.

## Samsara — the first adapter (derived from the published spec, not memory)

Samsara is the **first adapter onto this contract, not its definition.**
Every endpoint path, parameter, field name, type and limit below was read
out of the vendor's published OpenAPI document; nothing here is recalled.

| What | Value |
| --- | --- |
| Spec document | `https://developers.samsara.com/openapi/samsara-api.json` (indexed from `https://developers.samsara.com/llms.txt` → `https://developers.samsara.com/docs/openapi-spec.md`) |
| Spec version (`info.version`) | **2025-10-23** (OpenAPI 3.0.1, `x-original-swagger-version: 2.0`) |
| Retrieved | **2026-07-29**, `Last-Modified: 2026-07-29T13:08:10Z`, sha256 `2ed9a10c736189354662585f50ea6a756b73d5fecb6663b2ee122fdca994730e` |
| Supporting guides read the same day | `/docs/telematics.md` (updated 2025-10-23), `/docs/telematics-history.md` (2025-10-22), `/docs/rate-limits.md` (2025-10-22), `/docs/authentication.md` (2025-10-22), `/docs/response-codes.md` (2025-10-22) |

**No live Samsara account has ever been contacted.** Only public
documentation was fetched. See `services/ingestion/connectors/samsara/README.md`
for exactly what must be re-verified when an agency token arrives.

### Endpoint of record

`GET /fleet/vehicles/stats/history` (`operationId: getVehicleStatsHistory`),
base URL `https://api.samsara.com` (the spec also lists
`https://api.eu.samsara.com` and `https://api.ca.samsara.com`).

- `startTime`, `endTime` — **both required** per the spec, RFC 3339 with
  millisecond precision and timezones supported.
- `types` — **required**, and the spec pins a hard limit: *"You may list
  **up to 3** types"*. `obdOdometerMeters,gpsOdometerMeters,gpsDistanceMeters`
  is exactly three, so engine-time types **cannot** ride along in the same
  request — they are a second request. This is a spec constraint, not a
  design preference.
- `vehicleIds`, `tagIds`, `parentTagIds` — optional filters.
- `after` — the pagination cursor.
- Auth: `AccessTokenHeader`, `type: http`, `scheme: bearer` (spec-global
  `security`) — i.e. `Authorization: Bearer <token>`, a **header**, never a
  query parameter.

### Field mapping (spec types quoted)

| Samsara stat type | Spec type of `value` | Contract `measure` / `basis` | `unit` | `reading_kind` |
| --- | --- | --- | --- | --- |
| `obdOdometerMeters` | `integer`, `format: int64` — *"Number of meters the vehicle has traveled according to the on-board diagnostics."* | `distance` / `ecu_odometer` | `meters` | `cumulative_counter` |
| `gpsOdometerMeters` | `integer`, `format: int64` — *"Number of meters the vehicle has traveled according to the GPS calculations and the manually-specified odometer reading."* | `distance` / `gps_odometer` | `meters` | `cumulative_counter` |
| `gpsDistanceMeters` | `number`, `format: double` — *"Number of meters the vehicle has traveled since the gateway was installed, based on GPS calculations."* | `distance` / `gps_distance` | `meters` | `cumulative_counter` |
| `obdEngineSeconds` | `integer`, `format: int64` — *"Number of seconds the vehicle's engine has been on according to the on-board diagnostics."* | `engine_time` / `ecu_engine_time` | `seconds` | `cumulative_counter` |
| `syntheticEngineSeconds` | spec: *"The cumulative number of seconds the engine has run estimated based on when the engine is running"* | `engine_time` / `estimated_engine_time` | `seconds` | `cumulative_counter` |

Response shape (`VehicleStatsListResponse`): `data[]` — one entry per
vehicle carrying `id` (`VehicleId`, string), `name` (`VehicleName`, string)
and one array **per requested stat type**, each element
`{ time, value, decorations? }` with `time` an RFC 3339 UTC timestamp
(`components/schemas/time`) — plus `pagination` (`paginationResponse`:
`endCursor`, `hasNextPage`, both required).

### The vendor's own documented failure modes → Headway DQ issues

Each of these is quoted from the spec/guides, not inferred:

| Vendor statement | What Headway does |
| --- | --- |
| `obdOdometerMeters`: *"If Samsara does not have diagnostic coverage for a particular vehicle, the value for this stat type will be omitted."* | `telematics_ecu_odometer_absent` (warning) naming the vehicles that returned GPS readings but no ECU odometer. No GPS value is promoted into the ECU basis. |
| `gpsOdometerMeters`: *"You must provide a manual odometer reading before this value is updated… Odometer readings that are manually set will update as GPS trip data is gathered."* | `gps_odometer` is a distinct basis whose accuracy depends on a human-entered seed. Documented in `docs/connecting-your-data.md`; never treated as equivalent to `ecu_odometer`. |
| `gpsDistanceMeters`: *"…since the gateway was installed"* | A replaced or reconfigured gateway restarts the counter. A counter that goes **backwards** inside a day yields `telematics_counter_regression` (warning), `value` absent, both endpoints retained. Nothing is repaired. |
| Sample cadence is event-driven (guide: GPS distance/odometer *"Approx. every 1000 meters"*, OBD odometer *"Approx. every 30 seconds when the vehicle is in motion"*) | `max_sample_gap_seconds` is stored on every row; a day whose movement spans a gap over the declared threshold raises `telematics_sample_gap` (warning). Nothing is interpolated across it. |
| `429 Too Many Requests` with a `Retry-After` header — *"Suggested time to wait before retrying (in seconds). Example: `0.40235`"*; `GET fleet/vehicles/stats/history` is listed at **50 reqs/s** | The connector honours `Retry-After` (fractional seconds) and backs off; 5xx uses exponential backoff per the vendor's own guidance. |

### Read-only scopes an agency must grant — and nothing more

Quoted from the endpoint descriptions in the spec:

- `GET /fleet/vehicles/stats/history` — *"select **Read Vehicle Statistics**
  under the Vehicles category when creating or editing an API token."*
- `GET /fleet/vehicles` (roster lookup, optional) — *"select **Read
  Vehicles** under the Vehicles category."*

That is the whole ask. Headway requests **no write scope of any kind**, no
compliance/ELD scope, and no scope that grants driver-behavior data. Samsara
tokens also support **Tag Access**, which narrows a token to tagged objects —
an agency that tags its vanpool fleet can hand Headway a token that cannot
see anything else, and should.

### Data minimization — this is employee-monitoring data

Fleet telematics is **employee-monitoring data**: a van's movement history is
in practice a record of what a person did with their day. The connector
therefore collects the minimum that serves this contract — vehicle-level
distance and time — and enforces it with an **allow-list applied before
anything is hashed, landed or produced**: top level `data` + `pagination`;
per vehicle `id`, `name` and the requested stat series; per reading `time`
and `value`. Everything else is dropped **before the first write**, including
`externalIds` (whose own vendor spec example is a `payrollId`),
`nfcCardScans`, `decorations`, and any driver-identified field a future API
version adds. Driver records, hours-of-service/ELD logs, safety scores,
harsh-event records and dashcam references are **not requested and not
ingested**, and no setting turns them on; any future driver-identified
ingestion must be gated behind an explicit, documented opt-in with a
plain-language employee-data warning.

Note honestly what this does **not** achieve: these records are not
anonymous. Daily distance and engine hours per vehicle, combined with vehicle
assignments or run sheets an agency already holds, can locate an identifiable
operator over time. That is a characteristic of the data class. Treat rows of
this contract as employee records.

Consequence for the raw record: it is the exact bytes of the **minimized**
response, not of the wire response — a deliberate, governance-mandated
exception to Headway's usual "byte-identical to what the source sent",
recorded in handoff 0028. Minimization is deterministic, so content
addressing and idempotent re-polls are unaffected.

## Deliberately NOT implemented (and why)

- **Hours-of-service / ELD endpoints** (`GET /fleet/hos/logs`,
  `/fleet/hos/daily-logs`). The spec requires the *"**Read ELD Compliance
  Settings (US)**"* scope — a far broader grant than vehicle statistics —
  and these records are **driver** duty status, personally identifiable and
  CJIS-adjacent in handling. Mapping driver duty time onto a vehicle-day
  additionally needs driver-vehicle assignment data, another endpoint and
  another scope. The `duty_status_time` basis exists in this contract so
  that a future, separately-justified wave can land it without a contract
  break; **nothing populates it today**. Whether a typical agency's Samsara
  tier exposes HOS at all is an open question (handoff 0028).
- **`/fleet/vehicles/stats/feed`.** The vendor's own guide says the feed
  endpoint is *"better than the `/history` endpoint for synchronizing
  data"*. It is the right long-term ingest mode, but its cursor is account
  state we cannot exercise or reason about without a token — building a
  checkpointed cursor loop we cannot test would be guessing. `/history` is
  windowed, replayable and verifiable against fixtures today.
- **A maximum query window.** The published spec and guides pin **no**
  maximum time range for `/fleet/vehicles/stats/history`. Headway therefore
  invents none: it polls **one declared service day per request window** —
  a Headway operational choice, stated as such — and will adopt a vendor
  limit if one is ever published.
- **Any calculation.** See the honesty wall.

## Fitting other vendors without a rewrite (the reuse proof)

The contract deliberately contains no Samsara vocabulary. A second adapter
needs only to answer four questions, all of which are enum choices:

1. Which of its series is `distance` and which is `engine_time`?
2. Is each one read from the vehicle's diagnostic bus, derived from GPS with
   a human-entered seed, or accumulated by the gateway → `basis`.
3. Does it report a running total or a per-period amount → `reading_kind`.
4. What is its registered `source_system` label (plus the `_simulated`
   twin)?

Systems that report a per-period distance instead of an odometer land as
`reading_kind: period_total` with no endpoints — the same table, the same
lineage, the same DQ vocabulary. Systems that expose a third odometer
flavour add one `basis` enum value. Neither case touches the connector
framework, the topic, the canonical table's shape, or any consumer.

Concrete adapters for other telematics vendors are **not** in this wave and
their field names are **not** guessed here; each one must be derived from
that vendor's own published specification the same way Samsara's was
(handoff 0028, Open Questions).
