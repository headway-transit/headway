# headway-samsara — Samsara fleet-telematics connector

Polls a Samsara account's **vehicle stat history** one declared service day
at a time, reduces each API response page to a strict data-minimization
allow-list, lands those exact bytes content-addressed in the object store,
and produces an `object_ref` raw-record envelope to
`raw.telematics.vehicle_stats` (handoff 0028).

Wire contract: [`contracts/fleet-telematics.v0.md`](../../../../contracts/fleet-telematics.v0.md)
\+ [`fleet-telematics.v0.schema.json`](../../../../contracts/fleet-telematics.v0.schema.json).

---

## Read this before anything else

**Telematics distance is not revenue miles. Engine time is not revenue
hours.**

An odometer delta is everything the vehicle did — revenue service, deadhead,
the driver's lunch run, the trip to the tyre shop, and on a vanpool van that
lives at a participant's house, personal use. An engine-hour meter counts
the engine running, including idling in a car park.

So this connector, and the whole pipeline behind it, **computes nothing**.
It captures measured vehicle movement, labels how it was measured, records
where the measurement is blind, and stops. No VRM, no VRH, no VP-mode
figure is derived from any of it, and nothing in `services/calc/` reads the
canonical rows. Making these measurements reportable requires the FTA
vanpool rules quoted verbatim into `services/calc/REGULATORY_TRACKER.md` by
the NTD Compliance role, plus an agency-declared statement of which
vehicle-days were revenue service — a separate, compliance-gated wave
(handoff 0028, Open Questions).

## Data minimization — this is employee-monitoring data

**Fleet telematics is employee-monitoring data.** A vanpool van's movement
history is, in practice, a record of what a person did with their day. The
first partner agency has no records officer — oversight is HR plus external
counsel, and a data-classification program is only now being stood up — so
this connector collects the **minimum that serves the stated purpose**
(vehicle-level distance and time for VP-mode reporting) and nothing else,
**by construction rather than by convention**.

### What Headway asks Samsara for, and what it deliberately does not

One page for an HR or legal reviewer:

| | |
| --- | --- |
| **Requested** | Five vehicle-statistics series only: `obdOdometerMeters`, `gpsOdometerMeters`, `gpsDistanceMeters` (distance), `obdEngineSeconds`, `syntheticEngineSeconds` (engine runtime) — each a number and a timestamp, per vehicle. |
| **Kept from the response** | Per vehicle: the vendor's vehicle `id` and `name`. Per reading: `time` and `value`. That is the complete list. |
| **Never requested** | GPS positions (`gps`), `decorations` of any kind, ID-card scans (`nfcCardScans`), fault codes, fuel, speed, engine state, EV telemetry, or any other stat series. |
| **Never requested — driver-identified** | Driver records, driver ids or names, **hours-of-service / ELD duty logs**, driver-behavior or safety scores, harsh-event records, dashcam or video references. **None of it is ingested, and there is no setting that turns any of it on.** |
| **Dropped before landing** | `externalIds` (the vendor's own spec example for it is a **`payrollId`**), `nfcCardScans`, `decorations`, any driver object, and any other key the vendor sends that is not on the allow-list. |
| **Scope requested** | **Read Vehicle Statistics** only. Headway asks for no write scope, no ELD/compliance scope, and no scope that grants driver-behavior data. |

### The allow-list runs before the first write

An **allow-list** (not a blocklist — a blocklist would need updating every
time the vendor adds a field) is applied to every response **before anything
is hashed, landed or produced**:

- top level: `data` and `pagination` only;
- per vehicle: `id`, `name`, and the stat series that were requested;
- per reading: `time` and `value`.

Everything else is removed **before the first write**. It is never landed
"just in case", and a driver-identified field added in a future API version
is dropped automatically because it will not be on the list.

**This is a deliberate, governance-mandated exception to "the raw record is
the exact bytes as received."** The raw record is the exact bytes of the
*minimized* response. Say that plainly rather than implying otherwise:
Headway's usual promise is that a raw record is byte-identical to what the
source sent, and here it is byte-identical to what the source sent **after
the minimization filter**. Everything downstream is unchanged — the record
is still content-addressed, still immutable, still the anchor of every
lineage walk — and minimization is deterministic (allow-list filtering,
numeric literals preserved verbatim, canonical key order), so identical
responses still yield identical `record_id`s and re-polls stay idempotent.

Dropped key **names** are logged so the removal is auditable; dropped
**values** never are.

If a future wave needs any driver-identified field, it must arrive behind an
explicit, documented opt-in setting carrying a plain-language warning that
this is employee data whose collection may be subject to collective-bargaining
agreements, state employee-privacy law, and the agency's own governance
program. **No such setting exists today, because nothing needs one.**

### Honest note: this data is not anonymous

Even with no driver id anywhere in it, **vehicle movement history can locate
an identifiable operator over time.** Daily distance and engine hours per
vehicle, combined with vehicle assignments, rosters or block sheets the
agency already holds, can reconstruct who was driving and roughly what they
did. That is a characteristic of the data class, not a flaw in this
connector, and it does not go away because the driver column is absent.
Treat these records as employee data: access-controlled, retention-governed,
and covered by whatever classification program the agency adopts.

## Verification status — no live Samsara account has ever been contacted

This is the honest statement required before anyone relies on this code.

- **No agency credentials exist and none were used.** Nothing in this
  connector's development involved a Samsara account, a sandbox, a partner
  tenant, or any request to `api.samsara.com`. The only Samsara systems ever
  contacted were the **public documentation servers**, to fetch the
  specification named below.
- **Every endpoint path, query parameter, field name, type, limit and error
  behaviour was derived from the vendor's published OpenAPI document**, not
  from memory, a blog, or an SDK:

  | | |
  | --- | --- |
  | Spec document | `https://developers.samsara.com/openapi/samsara-api.json` |
  | Discovered via | `https://developers.samsara.com/llms.txt` → `https://developers.samsara.com/docs/openapi-spec.md` |
  | Spec version (`info.version`) | **2025-10-23** (OpenAPI 3.0.1; `x-original-swagger-version: 2.0`) |
  | Retrieved | **2026-07-29**, `Last-Modified: 2026-07-29T13:08:10Z` |
  | sha256 of the retrieved document | `2ed9a10c736189354662585f50ea6a756b73d5fecb6663b2ee122fdca994730e` |

  Supporting guides read the same day: `/docs/telematics.md` (updated
  2025-10-23), `/docs/telematics-history.md` (2025-10-22),
  `/docs/rate-limits.md` (2025-10-22), `/docs/authentication.md`
  (2025-10-22), `/docs/response-codes.md` (2025-10-22).

- **Anything the spec does not pin is not implemented.** See "Left
  unimplemented" below. A fabricated endpoint shape would be worse than no
  connector at all.
- **All test fixtures are synthetic and labelled as such.** They are built
  from the spec's own schemas (`VehicleStatsListResponse`,
  `paginationResponse`, `VehicleStats*WithDecoration`), never captured from
  a live account. Synthetic runs use the source label `samsara_simulated`,
  never `samsara`.

### What must be re-verified the day an agency token arrives

Nothing below can be settled without a real account. Treat this as the
acceptance checklist for the first live connection:

1. **Authentication and scope.** A token carrying ONLY "Read Vehicle
   Statistics" actually returns `/fleet/vehicles/stats/history` (and that
   Headway needs no other scope). Confirm the 401/403 message path.
2. **Real response shape.** That a live page matches
   `VehicleStatsListResponse` field-for-field, including whether
   `externalIds` and `decorations` appear, and whether any additional keys
   arrive that the normalizer will report as unmapped series.
3. **Pagination at real volume.** That `endCursor`/`hasNextPage` behave as
   documented across more than one page for a real fleet and a real day, and
   that page sizes stay inside `SAMSARA_MAX_PAGE_BYTES`.
4. **Rate limiting in practice.** That `429` really carries `Retry-After`,
   its real magnitude, and whether the documented 50 req/s endpoint tier is
   what the account experiences.
5. **Whether a maximum query window exists.** The published spec pins none.
   If a live request for a full service day is rejected or truncated, the
   window must be split — and the real limit recorded here.
6. **ECU odometer coverage.** Which vanpool vehicles actually return
   `obdOdometerMeters`, and how often. This decides whether ECU odometer is
   the practical basis for that fleet or whether GPS bases carry it.
7. **`gpsOdometerMeters` seeding.** Whether the agency has entered manual
   odometer readings at all — without one, the vendor documents this series
   as not updating. An unseeded GPS odometer is not a usable basis.
8. **Sample cadence and real gaps.** The real distribution of
   `max_sample_gap_seconds` on live vanpool days, which is what tells us
   whether the 6-hour gap warning default is useful or noisy.
9. **Counter resets.** Whether gateway replacements appear as the
   backwards-counter case this connector already detects, and at what rate.
10. **Engine-time availability.** Whether `obdEngineSeconds` returns
    anything for the fleet, or whether only `syntheticEngineSeconds`
    (the vendor's estimate) is present.
11. **Clock and timezone reality.** That sample timestamps arrive with the
    documented RFC 3339 UTC form, and that the agency's declared service-day
    timezone is the one it actually uses for vanpool accounting.
12. **Vehicle identity.** How the agency maps Samsara vehicle ids/names onto
    its own fleet roster. Headway stores the vendor id verbatim and makes no
    guess; this mapping is a human step that does not exist yet.

Until every item above is done against a real account, this connector is
**built and unit-verified, not field-verified**.

## Vendor API surface used

`GET /fleet/vehicles/stats/history` (`operationId: getVehicleStatsHistory`),
base URL `https://api.samsara.com` (the spec also lists
`https://api.eu.samsara.com` and `https://api.ca.samsara.com`).

- `startTime` / `endTime` — required, RFC 3339. Headway sends one **declared
  local service day** per window, with an explicit UTC offset.
- `types` — required, and capped by the spec at **three types per request**
  ("You may list ***up to 3*** types"). The distance set
  (`obdOdometerMeters,gpsOdometerMeters,gpsDistanceMeters`) is exactly three,
  so engine-time types **must** be a second request. That is a spec
  constraint, not a design choice.
- `after` — the pagination cursor from `pagination.endCursor`, followed
  while `pagination.hasNextPage` is true.
- `vehicleIds` / `tagIds` / `parentTagIds` — optional filters, passed
  through verbatim.
- Auth: `Authorization: Bearer <token>` (the spec's global
  `AccessTokenHeader`, `type: http`, `scheme: bearer`). A **header**, never a
  query parameter — which is also why the request URL is safe to log and to
  record as the envelope's `feed_url`.

**Scopes an agency must grant, and nothing more** (quoted from the spec's
endpoint descriptions):

- `GET /fleet/vehicles/stats/history` — *"select **Read Vehicle Statistics**
  under the Vehicles category when creating or editing an API token."*
- `GET /fleet/vehicles` — *"select **Read Vehicles**…"* — only if a roster
  lookup is added later; **this connector does not call it today**.

Headway asks for **no write scope of any kind** and no compliance/ELD scope.
Samsara tokens also support **Tag Access**, which restricts a token to
tagged objects: an agency that tags its vanpool fleet can issue a token that
cannot see anything else, and should.

## Left unimplemented (deliberately)

- **Hours-of-service / ELD endpoints** (`/fleet/hos/logs`,
  `/fleet/hos/daily-logs`). **Not needed for VP distance and time**, so under
  data minimization they are not implemented at all — not implemented and
  switched off, but absent. The spec requires the *"Read ELD Compliance
  Settings (US)"* scope — far broader than vehicle statistics — and these are
  **driver** records: personally identifiable, employee-monitoring data whose
  collection may engage collective-bargaining agreements and state
  employee-privacy law, CJIS-adjacent in handling, and a driver's regulated
  duty status is not a vehicle's revenue time anyway.
  Attributing driver duty time to a vehicle-day would additionally need
  driver-vehicle assignment data, another endpoint and another scope. The
  contract reserves a `duty_status_time` basis so a future, separately
  justified wave can land it without a contract break; nothing populates it.
- **`/fleet/vehicles/stats/feed`.** The vendor's own guide says the feed
  endpoint is *"better than the `/history` endpoint for synchronizing
  data"*, and it is the right long-term ingest mode. Its cursor is account
  state that cannot be exercised or reasoned about without a token; a
  checkpointed cursor loop that has never seen a real cursor would be
  guesswork. `/history` is windowed, replayable and verifiable against
  fixtures today.
- **A maximum query window.** The spec and guides pin none, so none is
  invented. Headway polls one service day per window — a Headway operational
  choice, stated as such — and will adopt a vendor limit if one is published.
- **A vehicle-roster join.** Samsara vehicle ids are stored verbatim; nothing
  maps them onto the agency's fleet inventory. That mapping is a human,
  agency-confirmed step and does not exist yet.
- **Any calculation.** See the top of this file.

## Configuration

The connector is switched on by `SAMSARA_ENABLED=true`. The **token is
deliberately not the on-switch**: a missing token must be a loud refusal,
never a connector that quietly never runs.

| Variable | Required | Meaning |
| --- | --- | --- |
| `SAMSARA_ENABLED` | yes | `true` starts the connector |
| `SAMSARA_API_TOKEN` | yes | Bearer token from the secret store. **Never logged**, never in an error message, never in a record |
| `SAMSARA_SOURCE` | yes | Envelope source label — `samsara` (real account) or `samsara_simulated` (anything synthetic). No default; unregistered labels are refused |
| `SAMSARA_SERVICE_DAY_TZ` | yes | Agency IANA service-day timezone, e.g. `America/New_York`. Must match the transform's `HEADWAY_TELEMATICS_SERVICE_DAY_TZ` |
| `SAMSARA_BASE_URL` | no | Default `https://api.samsara.com`; use the EU/CA host for an EU/CA-hosted account |
| `SAMSARA_VEHICLE_IDS` / `SAMSARA_TAG_IDS` / `SAMSARA_PARENT_TAG_IDS` | no | Vendor-side filters, comma-separated |
| `SAMSARA_ENGINE_TIME` | no | `false` skips the engine-runtime request (default on). Engine runtime is **not** duty hours |
| `SAMSARA_LAG_DAYS` | no | Newest polled service day = today − this (default 1) |
| `SAMSARA_BACKFILL_DAYS` | no | Consecutive service days re-polled per cycle (default 3) |
| `SAMSARA_POLL_INTERVAL` | no | Cycle cadence, Go duration (default `6h`). Separate from `POLL_INTERVAL`: a daily-window API is not a 30-second feed |
| `SAMSARA_MAX_PAGE_BYTES` | no | Cap on one response page (default 64 MiB) |

`S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` are required
(pages are landed before they are produced) and `KAFKA_BROKERS` as for every
connector.

`SAMSARA_LAG_DAYS`, `SAMSARA_BACKFILL_DAYS` and `SAMSARA_POLL_INTERVAL`
defaults are **Headway operational choices, not vendor limits**: a service
day is not complete until it ends, and gateways upload late.

## Behaviour

- **Fail closed.** Missing token, missing/unregistered source label, or
  missing service-day timezone → the connector refuses to start with a
  plain-language message naming the fix. It never guesses a default.
- **Secrets never logged.** The token exists only in an `Authorization`
  header. Tests assert it appears in no log line, no error string and no
  produced envelope.
- **Minimize, then store, then produce.** The allow-list runs first; the
  minimized bytes are landed at `raw/telematics/<record_id>.json`; only then
  is the envelope produced, so a consumer can never see an envelope whose
  object is missing.
- **Content-addressed and idempotent.** `record_id` is the SHA-256 of the
  exact bytes landed (the minimized response); identical re-polls are no-ops
  downstream. Within a process, an identical page is not even re-produced.
- **Fail loudly.** A page that is not the documented response shape — or
  whose structure does not permit minimization — is still landed and produced
  with `parse_status: "malformed"` and a `parse_error` (evidence of a failure
  is never destroyed, and such a page cannot carry vendor-defined driver
  records anyway, because the requested token scope does not grant them);
  pagination then stops rather than following a cursor Headway could not
  read. An empty 200 body, an oversize page and a stuck cursor are all loud
  errors, never silent skips.
- **Rate limits and server errors.** `429` honours the documented
  `Retry-After` header (seconds, possibly fractional — the vendor's own
  example is `0.40235`), capped by `DefaultMaxRetryWait`. `5xx` uses
  exponential backoff, as the vendor's response-codes guide asks. Other
  `4xx` are not retried.

## Operational prerequisite

The topic `raw.telematics.vehicle_stats` must exist on the broker. It is
registered in `contracts/topics.v0.md`, but the Compose stack's
`bootstrap-kafka` topic list (`deploy/compose/compose.yaml`) still needs it
added — a one-line DevOps change outside this wave's scope. Until then the
connector fails loudly at produce time with
`UNKNOWN_TOPIC_OR_PARTITION` (observed, and correct behaviour).

## Tests

```sh
cd services/ingestion && go test ./connectors/samsara/ -v
```

Covers: the registered-source list matching the checked-in contract enum;
the vendor's three-type limit; fail-closed refusals (each message asserted,
and asserted not to contain the token); the happy path down to a landed
object whose bytes are exactly what `record_id` hashes, with every measured
value preserved verbatim, and a token-free `feed_url`; store-before-produce; cursor
pagination and a stuck-cursor refusal; `429` + `Retry-After` and `5xx`
exponential backoff; `401` naming the scope without echoing the token;
malformed and shape-incomplete pages landed with `parse_status: malformed`;
empty and oversize bodies refused; identical vs changed re-polls; DST-correct
23/25-hour service-day windows; the backfill span; and **data minimization** —
a response padded with `externalIds`/`payrollId`, `nfcCardScans`/badge ids, a
driver object and per-sample GPS decorations lands with none of them present,
the dropped key names logged and the dropped values not, the allow-list
verified key-by-key, numeric literals preserved verbatim, minimization proven
deterministic, an unminimizable page still landed as malformed, and the
request surface pinned so no driver-identified stat type can be added
silently.
