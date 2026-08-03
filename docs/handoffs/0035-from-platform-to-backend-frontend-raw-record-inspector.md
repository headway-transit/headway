# Handoff: platform → backend+frontend — The raw-record inspector (the end of the trail)

## Context
First-agency UAT, the sharpest finding of the week (ITS manager, 2026-07-30). He did
exactly what the platform is built for — walked a VRH figure back through its lineage to
the source — and hit a wall of hashes labeled *"raw source record as received — the end
of the trail."* His verdict: **"It doesn't really provide any data to validate or
verify."**

He is right. The content address genuinely proves tamper-evidence (change one byte and
the id no longer matches), but proof you cannot *inspect* asks for trust at the exact
step where this platform must never ask for trust. The chain of custody currently ends
with a sealed evidence bag that has **no label and no window**.

## Design (binding)

1. **`GET /raw/records/{record_id}` — the label.** Serves the record's metadata:
   source, connector + version, fetched_at, content_type, payload encoding, byte size,
   parse_status, the object-store key, and the id itself. Authz: viewer+ (same surface
   as the lineage walk it completes); audited. Never invents a field — absent is absent.
2. **Integrity, as an action rather than a claim.** `POST /raw/records/{id}/verify`
   re-reads the stored bytes, re-computes the SHA-256, and reports **match / mismatch**
   with both digests shown. This turns "content-addressed and immutable" from marketing
   into a button the auditor presses. A mismatch is a loud, unmissable alarm (and would
   itself be a finding — record how it surfaces).
3. **`GET /raw/records/{id}/payload` — the window.** Bounded (documented cap, honest
   truncation note) preview:
   - **GTFS-Realtime protobuf** → decoded, human-readable: feed timestamp, entity count,
     and the first N vehicles/trip updates with their real values. This is the moment a
     steward sees *their own bus, at that minute, at those coordinates* as the origin of
     a number.
   - **CSV / text** → first N rows verbatim (headerless positional files rendered with
     the registered adapter's column names where a label is known — never guessed).
   - **Anything else / undecodable** → say so plainly, offer the raw download.
   - Plus `GET .../download` for the exact bytes.
   Sensitivity: this is agency operational data; the classification doc governs
   (docs/data-classification.md). Paratransit payloads carry rider coordinates —
   **preview must respect the same withholding the analyst role enforces**; decide and
   record the rule (recommendation: gate DR-source payloads to the roles allowed
   coordinates, refuse in plain words otherwise).
4. **Frontend: the lineage leaf becomes readable.** In the receipt/lineage view, each
   raw-record leaf shows the label inline (source · connector · fetched_at · size ·
   parse_status), a **Verify integrity** action with its verdict rendered plainly, and an
   expandable payload preview. The hash stays visible — demoted to the footnote it should
   always have been. Keep the text-view/graph-view parity that exists today.
5. **Honest scope:** read-only; no re-parsing, no editing, no re-ingestion; no
   full-payload rendering of multi-MB files in the browser (bounded preview + download);
   the decoder set is GTFS-RT + CSV/text in v0 — everything else states its type and
   offers bytes.

## Outputs
API tests (authz matrix, verify match AND mismatch paths, bounded preview, unknown type,
missing object, sensitivity refusal) + suite green; openapi regenerated; web tests + axe
+ contrast green; live verification against REAL records on this box (a GTFS-RT frame
decoded to actual vehicles; a vendor CSV previewed; one integrity verify shown passing)
with screenshots; evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- Object-store outage behavior (metadata without payload — degrade honestly).
- Whether verify should be offered in bulk (a "verify this figure's whole evidence
  chain" action) — likely the natural v1 and a superb demo.
- Decoders for the remaining contract types (TIDES, DR, telematics envelopes).

## Outputs — evidence
(appended by the implementing agent)

### Response — backend + frontend (2026-07-30)

Contract accepted and shipped in full. Everything below was measured on THIS
box against REAL records: host uvicorn on 127.0.0.1:8000 (restarted three
times, environment restored byte-for-byte from `/proc/<pid>/environ` plus the
one new setting below), the live TimescaleDB, the live MinIO bucket
(`headway-raw`, 27 objects) and the live Kafka broker (60,281 GTFS-Realtime
frames on `raw.gtfs_rt.vehicle_positions`), through the live Vite dev server
with real logins. Nothing in this section is a fixture.

---

#### 1. The finding underneath the finding: half the raw records were not where the handoff assumed

The handoff's premise was that the object store holds the raw records. It
holds *most* of them. It does **not** hold the ones the UAT walk actually
ended at.

```
source            payload_encoding  payload_ref  count
gtfs_rt           base64            NULL         55,784      <-- no object
gtfs_static       object_ref        raw/gtfs_static/…zip          6
tides_simulated   object_ref        raw/tides/…csv                5
samsara_simulated object_ref        raw/telematics/…json          6
dr_simulated      object_ref        raw/dr/…csv                   3
tripspark_streets object_ref        raw/vendor/…csv               2
acme_*_simulated  object_ref        raw/vendor/…csv               2
```

`raw.records` is an **index**, not a payload table (migration 0002), and the
GTFS-Realtime connector never writes to the object store: it base64-encodes
the exact bytes into the ingest envelope and produces it to
`raw.gtfs_rt.*` keyed by `record_id` (`services/ingestion/connectors/gtfsrt`,
contracts/topics.v0.md). The broker is the only place those bytes exist.

That is 99.9% of the raw records on this box, and — decisively — **the leaves
of every VRM/VRH lineage that comes from realtime**: one live VRH figure
(`05b41773…`) has 1,138 raw leaves, all of them `gtfs_rt`. An inspector that
read only the object store would have opened the evidence bag for TIDES and
paratransit files and shown the auditor the same wall of hashes for the exact
case he complained about.

So the payload reader resolves bytes from **two** places, chosen by the
record's own `payload_encoding`, behind one injectable seam
(`headway_api/raw_payloads.py`):

| Encoding | Reader | How |
| --- | --- | --- |
| `object_ref` | `ObjectStorePayloadReader` | MinIO `stat_object` for the label's size (no object read); streamed `get_object` for verify and download |
| `base64` | `EnvelopeStreamPayloadReader` | **bounded** broker lookup: `offsets_for_times(fetched_at − 5 min)`, scan ≤ 400 messages for the message keyed with this `record_id`, and **re-hash the payload before returning it** — the message key alone is not trusted as proof of identity |

Measured live: the bounded lookup finds a frame after **5 messages**, and the
whole verify round trip is **0.217 / 0.231 / 0.226 s** (3 runs). The label,
which deliberately reads no bytes at all, is **2.3–2.6 ms**.

`KAFKA_BROKERS` is now read by the API for a second purpose (it was
producer-only). It was **added** to the live process — the only environment
change; every other variable, including `HEADWAY_SESSION_SECRET`, was
restored byte-for-byte so signed-in sessions survived each restart. Without
it, `base64` payloads refuse with a plain 503 that names the missing setting.

**This exposed a real platform gap, and it is recorded rather than papered
over:** once the broker's retention window passes, a GTFS-Realtime record's
bytes are **gone**. On this box the window starts at **2026-07-23 14:33 UTC**
(offset 39,271 of 60,281), so every figure computed before that walks back to
records Headway can no longer show or re-verify. That is not a defect in this
endpoint — it is an ingestion/deployment decision — and the API says so in
those words (410 `not_retained`, screenshot below), raises **no** DQ finding
for it, and does not pretend. Durable retention for realtime frames belongs
in a handoff to ingestion/DevOps; it is named in "Still unproven" below.

#### 2. Endpoints

| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| GET | `/raw/records/{id}` | any signed-in | The label. `raw.records` columns verbatim + where the bytes live + measured size + content address + the sensitivity rule + which decoder applies. Reads **no** payload. |
| POST | `/raw/records/{id}/verify` | any signed-in | Re-read, re-hash, verdict with both digests. **200 match / 409 mismatch / 404 bytes missing / 410 not retained / 503 storage unavailable.** |
| GET | `/raw/records/{id}/payload` | any signed-in **+ sensitivity gate** | Bounded decoded preview; every cap in the response. |
| GET | `/raw/records/{id}/download` | any signed-in **+ sensitivity gate** | Exact stored bytes, streamed. |

`openapi.json` regenerated: OpenAPI 3.1.0, **67 paths** (was 63).

**The status codes are the design, not decoration.** A mismatch returning
`200 {"result": "mismatch"}` would let any caller that checks `response.ok`
record a pass. It returns **409** with the full verdict in the body; the web
client is the one call in `api/client.ts` that deliberately reads the body on
a non-2xx, because the failing body is the verdict the auditor came for.

**A failing verdict is also a finding.** Mismatch raises a blocking
`dq.issues` row (`raw_record_integrity_mismatch`); bytes missing from the
object store raise `raw_record_payload_missing`. Both are **idempotent** —
the endpoint looks for an unresolved issue of that type against that record
first, so pressing the button five times files one finding, not five. The
issue insert and the audit row commit in **one transaction**: audit logging
is never best-effort, so a verification that cannot be logged fails.

#### 3. The decoder set (v0), and what it refuses to guess

| Decoder | Selected when | Shows | Cap |
| --- | --- | --- | --- |
| `gtfs_realtime` | `source=gtfs_rt` and `content_type=application/x-protobuf` | Feed version, incrementality, header timestamp, entity count and kinds, then per entity: vehicle id + **label**, route, trip, direction, lat/lon, bearing, speed, event time, current status, stop, occupancy — plus trip-update and alert shapes | **25 entities**, 3 stop-time updates each, 4 MiB read |
| `delimited_text` | `text/csv` from `headway-tides`, `headway-dr`, `headway-api-ingest` | The file's **own first row** as the header (their contracts declare a header row; the ingest header check reads exactly this dialect) + rows | **20 rows**, 500 chars/cell, 4 MiB read |
| `text` | any other `text/*` or `application/json` | Lines **verbatim**, no delimiter inferred, **no column names** | 20 lines, 500 chars/line |
| `none` | everything else (e.g. `application/zip`) | Content type, size, and the exact bytes to download | reads 0 bytes |

Decoded with `gtfs-realtime-bindings` — the **same pinned Apache-2.0
bindings `services/transform` normalizes with** — so what an auditor reads in
a preview is what the pipeline read. Added to `headway-api[ingest]` alongside
`python-snappy>=0.7` (the Go producer snappy-compresses batches; ≥0.7 is a
pure-Python shim over cramjam, so no `libsnappy-dev` and no C toolchain enters
the image — the `services/transform` Dockerfile precedent).

Three refusals to guess, each deliberate:

- **Vendor exports get no column names.** `tripspark_streets` and
  `acme_paravan_simulated` are pipe- and semicolon-delimited with vendor
  field names; what those columns MEAN is defined only by the registered
  mapping spec (`adapters/<vendor>/<product>/mapping.v0.yaml`), which the API
  does not hold. Guessing a delimiter or borrowing a schema would put
  fabricated labels on real data. Lines are shown exactly as stored, and the
  preview says why.
- **A byte-truncated last row is dropped**, not shown half-real (the 9.9 MB
  TIDES CSV previews 19 rows, not 20, for exactly this reason).
- **A protobuf frame larger than the 4 MiB read cap is not partially
  decoded** — a feed message must be read whole; the preview says so and
  offers the bytes.

`truncated` is honest in both directions: a file that fits inside the cap
reports `"This is the whole file: 1 line, exactly as stored."` rather than
"showing the first 1 line", which would imply lines that do not exist.

#### 4. The sensitivity rule (recorded decision)

> **A raw record's CONTENTS are withheld from the broadest read role when the
> payload can carry rider pickup/dropoff coordinates. Its LABEL and its
> INTEGRITY CHECK are never withheld from anyone.**

| Class | Applies to | Minimum role | Basis |
| --- | --- | --- | --- |
| `rider_location` | connector `headway-dr`, **or** an object key under `raw/dr/` | `data_steward` | docs/data-classification.md: paratransit pickup/dropoff coordinates are rider home and destination addresses, and an ADA trip record can disclose disability status by its existence. Migration 0028 already withholds exactly these columns from the read-only analyst role; a raw record is as sensitive as the payload inside it. |
| `undetermined` | every `headway-vendor-file` export | `data_steward` | The raw-record index does not record which open contract a vendor label maps to — and the reference `acme/paravan` spec targets `demand_response_trip`. Fail closed. |
| `internal` | everything else | `viewer` | Agency operational data. |

Three sub-decisions worth naming:

- **The object-key prefix, not the connector, separates DR from TIDES**: the
  machine-ingest connector (`headway-api-ingest`) lands both, so
  `raw/dr/…` is the discriminator. Pinned by test.
- **Classified from the record's own ingest metadata, never from downstream
  evidence.** Joining `canonical.dr_trips.source_record_id` would have been
  more precise and would have leaked: a paratransit file that has landed but
  not yet been transformed must be withheld from the second it exists.
- **Telematics is deliberately NOT tightened.** docs/data-classification.md
  calls Samsara-class data "Employee data", but the platform's stated control
  for it is *minimisation at the connector* (handoff 0028), not withholding
  at read, and migration 0028 does not withhold it from the analyst role.
  Inventing a second rule here would be inventing policy. Recorded so a
  governance program can tighten it deliberately.

Refusals are 403s that say why, in the user's own language, and the record's
label and Verify button stay live — **the chain of custody is never broken,
only the window is closed.**

#### 5. Live verification — the decoded GTFS-Realtime preview

`GET /raw/records/cd7e5550…/payload` as `dsteward`, HTTP 200 in 0.237 s,
against a frame that had landed **15 seconds** earlier:

```
size_bytes  = 67246          read_from = ingest_envelope_stream
decoder     = gtfs_realtime  truncated = True
truncation_note = Showing the first 25 of 599 entities in this feed message.
                  The remaining entities are in the bytes you can download;
                  nothing was dropped from the record.
caps        = {max_entities: 25, max_stop_time_updates_per_entity: 3,
               max_bytes_read: 4194304}
gtfs_realtime_version = 2.0     incrementality = FULL_DATASET
header_timestamp      = 1785453964  -> 2026-07-30T23:26:04Z
entity_count = 599   entity_kinds = {vehicle: 599, trip_update: 0, alert: 0}

  { "entity_id": "R-548B0D89", "kind": "vehicle_position",
    "vehicle_id": "R-548B0D89", "vehicle_label": "1960",
    "trip_id": "ADDED-1584638337", "route_id": "Red", "direction_id": 1,
    "latitude": 42.28200912475586, "longitude": -71.06208801269531,
    "bearing": 330.0, "speed": null,
    "timestamp": 1785453694, "timestamp_utc": "2026-07-30T23:21:34Z",
    "current_status": "IN_TRANSIT_TO", "stop_id": "70094",
    "occupancy_status": null }

  { "entity_id": "y1221", "kind": "vehicle_position",
    "vehicle_id": "y1221", "vehicle_label": "1221",
    "trip_id": "77139759", "route_id": "28", "direction_id": 0,
    "latitude": 42.336429595947266, "longitude": -71.0899887084961,
    "bearing": 45.0, "speed": null,
    "timestamp": 1785453953, "timestamp_utc": "2026-07-30T23:25:53Z",
    "current_status": "STOPPED_AT", "stop_id": "17865",
    "occupancy_status": "MANY_SEATS_AVAILABLE" }

  { "entity_id": "ynk230", "kind": "vehicle_position",
    "vehicle_id": "ynk230", "vehicle_label": "230",
    "trip_id": "BL-40770992", "route_id": "Shuttle-Generic",
    "direction_id": null, "latitude": 42.36253356933594,
    "longitude": -71.08747863769531, "bearing": null, "speed": null,
    "timestamp": 1785453953, "timestamp_utc": "2026-07-30T23:25:53Z",
    "current_status": "IN_TRANSIT_TO", "stop_id": null,
    "occupancy_status": null }
```

Bus **1221 on route 28, stopped at stop 17865 at 23:25:53 UTC** — read out of
the record's own bytes, at the end of a lineage walk. That is the sentence
the wave existed to make possible. Note the third entity: no direction, no
bearing, no stop — **absent renders absent**, never a zero.

Rendered in the UI (real login, live Vite):
`docs/images/handoff-0035/gtfsrt-decoded-live.png` — reached by walking
`headway_adherence` figure `b6e803ab…` → Text view → a raw leaf → Verify
integrity (2,702 bytes, match) → Look inside → 25 of 28 entities with their
vehicles, routes, trips, positions and times.

#### 6. Live verification — the integrity button, both verdicts

**Match**, against the object store and against the broker:

```
POST /raw/records/cd7e5550…/verify   HTTP 200 in 0.235 s
  result          = match
  algorithm       = sha-256
  expected_digest = cd7e5550eb77f29bc4c537a444195042ab3c09bca5c0012d15aa5dd25f5bd3ce
  actual_digest   = cd7e5550eb77f29bc4c537a444195042ab3c09bca5c0012d15aa5dd25f5bd3ce
  size_bytes      = 67246       read_from = ingest_envelope_stream
  headline        = Verified: the stored bytes are unaltered.
  detail          = Headway re-read all 67,246 bytes from the ingest envelope
                    stream and re-computed their SHA-256. It matches this
                    record's id exactly, so the bytes have not changed since
                    Headway received them.
```

**Mismatch — the integrity drill.** To prove the alarm on real storage, one
byte of a stored payload was deliberately altered and then restored. The
record chosen was `dr_simulated` (synthetic demo data, already consumed by
the transform months of pipeline-time ago); `raw.records` itself was never
touched (it is immutable by trigger). The change was the smallest and least
visible possible — a pickup latitude `42.23499` → `42.23498`, one character,
same file length:

```
original  14,621 bytes  sha256 3cd0f7d5…0ceaa   (== the record id)
tampered  14,621 bytes  sha256 963287be…f277d26

POST /raw/records/3cd0f7d5…/verify     HTTP 409
  result       = mismatch
  actual_digest= 963287befbade4e57812c5a4fe6d69c133d144d5f35b497e1b8165e78f277d26
  headline     = MISMATCH: the stored bytes are NOT the bytes this record was
                 created from.
  detail       = … The two disagree, which means the stored copy has been
                 altered or corrupted. Treat every figure that cites this
                 record as unproven until someone explains the difference. A
                 blocking data-quality issue has been raised so this cannot be
                 quietly forgotten.
  dq_issue_id  = 5a1c9eaf-e75e-4ff9-bfba-64808759d3a4   (blocking, open)

restore   14,621 bytes  sha256 3cd0f7d5…0ceaa   identical: True
POST …/verify                          HTTP 200   result = match
```

The finding was then resolved through the ordinary `/dq` workflow with a
resolution note recording that it was a deliberate drill and that the bytes
were restored byte-for-byte. **The drill is itself part of the evidence: the
alarm fired on a one-character change, and the restore was proven by hash,
not by assertion.**

Screenshots: `verify-match-live.png`, `verify-mismatch-live.png`.

**Honest degradation** (`not-retained-live.png`), on a `days_operated` figure
whose single GTFS-Realtime leaf was fetched 2026-07-11 — before the broker's
retention window:

```
POST /raw/records/06826153…/verify     HTTP 410
  result = unavailable   reason = not_retained   actual_digest = null
  dq_issue_id = null          <-- deliberately NOT a finding
  detail = This record's bytes rode inline in the ingest envelope rather than
           being written to the object store, and the broker no longer retains
           that message. The record's identity and its place in the trail are
           unaffected — but Headway cannot show you these bytes or re-verify
           them. Retaining realtime frames for longer is a deployment setting,
           not something this screen can fix.
```

#### 7. Live verification — the other decoders, the download, and the gate

| Record (live) | Result |
| --- | --- |
| `66d24dc6…` TIDES CSV, 9,966,503 B | 200 in 41 ms; header = `passenger_event_id, service_date, event_timestamp, trip_id_performed, …`; 19 rows (the 20th was byte-truncated and dropped); `truncated: true` |
| `fab57945…` `tripspark_streets` vendor CSV, 6,825 B | 200 in 11 ms; decoder `text`; lines verbatim; note: *"Headway does not know this file's column names from the record alone — only the registered mapping spec for this source defines them — so no column labels are shown rather than guessed ones."* |
| `21113960…` GTFS static zip, 24,448,677 B | 200 in 7 ms; decoder `none`; **0 bytes read**; states the type and offers the bytes |
| `0c181f63…` telematics JSON, 368 B | 200 in 6 ms; decoder `text`; *"This is the whole file: 1 line, exactly as stored."* |
| `a043ba42…` DR CSV as **viewer** | **403** — the withholding sentence, verbatim in §4 |
| `a043ba42…` DR CSV **verify** as **viewer** | **200 match** — integrity is never gated |
| `3cd0f7d5…` DR CSV as **dsteward** | 200; header includes `pickup_lat, pickup_lon, dropoff_lat, dropoff_lon`; 16 rows of real coordinates |
| `3cd0f7d5…` DR **download** as **viewer** | **403** |

**Download round-trip, hashed:**

```
GET /raw/records/05d346d0…/download
  content-disposition: attachment; filename="05d346d0….pb"
  x-headway-record-id: 05d346d0e08cb29a780b4936e4fef4993b3d1d12eba31583fea50a359a5c9e54
  x-headway-content-address: sha-256:05d346d0…
  content-length: 2702      content-type: application/x-protobuf
  sha256sum of the saved file == the record id                     ✅

GET /raw/records/21113960…/download   (the 24 MB GTFS static zip)
  HTTP 200, 24,448,677 bytes in 0.079 s; sha256sum == the record id ✅
POST /raw/records/21113960…/verify    HTTP 200 in 0.054 s
```

24 MB verified in 54 ms because verification streams a megabyte at a time
(`MinioObjectStore.stream`, added this wave) rather than holding the object.

**Audit trail, queried from `audit.events` after the session:**

```
1087 dsteward raw_record_verify          cd7e5550… {"result":"match","read_from":"ingest_envelope_stream",…}
1088 dsteward raw_record_payload_preview cd7e5550… {"decoder":"gtfs_realtime","bytes_read":67246,"sensitivity":"internal"}
1093 vread    raw_record_verify          a043ba42… {"result":"match","read_from":"object_store",…}
1094 dsteward raw_record_payload_preview a043ba42… {"decoder":"delimited_text","bytes_read":5130,"sensitivity":"rider_location"}
1096 dsteward raw_record_payload_preview fab57945… {"decoder":"text","bytes_read":6825,"sensitivity":"undetermined"}
1097 dsteward raw_record_payload_preview 21113960… {"decoder":"none","bytes_read":0}
1115 dsteward raw_record_verify          06826153… {"reason":"not_retained","result":"unavailable","dq_issue_id":null}
1117 dsteward raw_record_verify          3cd0f7d5… {"result":"mismatch","dq_issue_id":"5a1c9eaf-…",…}
1118 dsteward raw_record_verify          3cd0f7d5… {"result":"match",…}
```

Every look inside is recorded, whatever the class; reading the label is not
(like every other signed-in GET); a **refused** look writes nothing, because
nothing was read.

#### 8. The lineage leaf, opened (frontend)

`web/src/components/RawRecordInspector.tsx`, reached from both renderings.

The copy that the UAT auditor hit is gone:

```
- rawLeaf: "raw source record as received — the end of the trail"
+ rawLeaf: "raw source record, exactly as Headway received it"
```

Each leaf now carries **"Open the raw source record <full id>"**, and opening
it discloses, in this order: the **label** (source + SIMULATED badge where
applicable, who collected it and at what version, when it was received, file
type, size, whether it could be read on arrival — with the parser's own error
verbatim when it could not, and where the bytes are held); the **fingerprint,
demoted to a footnote** in small caps under the label with the one sentence
that explains what it proves; then **Verify integrity**, **Look inside**, and
**Download the exact bytes**.

- A **pass** is a `role="status"` panel with both fingerprints listed and the
  server's own sentences verbatim.
- A **MISMATCH** is a `role="alert"` panel: heading `INTEGRITY CHECK FAILED`,
  a warning-triangle icon, a 3px border, both digests, and the raised DQ
  finding named **with a link into `/dq/issues/{id}`**. It is loud by
  heading, icon, border weight and words — it survives a monochrome print-out
  and a screen reader. `role="status"` vs `role="alert"` is the difference an
  assistive-technology user hears.
- A **withheld** payload shows a banner with the server's refusal verbatim,
  disables "Look inside", hides "Download", and leaves **Verify integrity
  enabled** (`dr-withheld-viewer-live.png`).
- The **cap is stated before the data**, never after.

**View parity kept.** In the graph view each raw node became an activatable
button (`onSelectRaw`) whose accessible name is *"Open the raw source record
<full id>"* — the complete id is still in the name — and activating it opens
the SAME component in a labelled panel beneath the graph. Keyboard path
unchanged: arrows walk the tiers, Enter expands the raw group and Enter opens
a record. Pinned by two tests.

**One deviation from the handoff's wording, and why.** Design point 4 says
each leaf "shows the label inline". Leaves open **on demand** instead. The
live VRH figure `05b41773…` has **1,138 raw leaves**; fetching a label for
each on page load is 1,138 requests — the 850 MB `/dq` mistake handoff 0030
spent a wave removing, in a new costume. Every leaf advertises the way in and
one click opens it; the label itself costs 2.4 ms.

**Live keyboard walk** (headless Chrome over CDP, real login, live data),
starting from a leaf's own toggle:

```
tab 1: BUTTON: Verify integrity
tab 2: BUTTON: Look inside [aria-expanded=false]
tab 3: BUTTON: Download the exact bytes
tab 4: BUTTON: Open the raw source record 066ca3af4baa8eb6afe79… [aria-expanded=false]
tab 5: BUTTON: Open the raw source record 0a5f14b90f96ecb9e2391… [aria-expanded=false]
tab 6: BUTTON: Open the raw source record 0ab4c8dbb8ced0ecfea2b… [aria-expanded=false]
Enter on: Open the raw source record 0ab4c8db… -> focus stays on the control,
          which becomes "Close this record" [aria-expanded=true]
```

No trap, logical order, `aria-expanded` truthful on every disclosure, focus
never jumps.

`jest-axe` clean on every new state (label, pass, MISMATCH, decoded preview,
withheld banner, graph panel). One real axe defect was found and fixed during
the wave: the preview's `<h4>` skipped a heading level, because this component
is embedded at a tree depth the page owns — it is now a labelled `<section>`
with a styled paragraph instead of an invented heading level.

#### 9. Tests, contract, gates

| Gate | Result |
| --- | --- |
| `pytest -q` (services/api) | **460 passed** (was 418; **+42** in `tests/test_raw_records.py`) |
| `npx vitest run` (web) | **286 passed / 38 files** (**+12** in `src/test/rawRecord.test.tsx`; 6 in `lineage.test.tsx` updated for the opened leaf) |
| `npx tsc --noEmit` | clean |
| `npm run lint` (oxlint) | clean |
| `npm run build` | built |
| `npm run check:contrast` | **All token pairs meet WCAG 2.1 AA** (light + dark) |
| `openapi.json` | regenerated — OpenAPI 3.1.0, **67 paths** |

The 42 API tests cover: the authz matrix (unauthenticated on all four
endpoints; label + verify open to all four roles including for a withheld
payload); verify **match** and **mismatch** (with the blocking finding, its
idempotence, and both digests); bytes **missing** (404 + its own finding);
retention **expired** (410, explicitly **no** finding); storage
**unconfigured** (503); the bounded GTFS-RT preview (real frames built with
the pinned bindings, the entity cap with the true total, absent-stays-absent,
an undecodable frame); the CSV header from the file's own first row, the row
cap, whole-file honesty, non-UTF-8 refusal; the vendor export shown without
invented column names; the unknown type; **sensitivity** (viewer refused on
paratransit and on vendor exports, stewards allowed, the DR-via-machine-API
key-prefix case, the label's `preview_allowed`); download byte-fidelity and
its refusal path; and the audit rows for every look, including that a refused
look writes none.

The API tests use the **real** `CompositeRawPayloadReader`,
`ObjectStorePayloadReader`, hashing and decoders over a fake store and a fake
broker lookup — only the topic scan is stubbed, so routing, streaming,
hashing and decoding under test are production code paths.

#### 10. Deviations from the handoff

1. **Leaves open on demand rather than inline** (§8) — 1,138-leaf trees.
2. **The decoder set stayed exactly GTFS-RT + CSV/text.** A GTFS static zip
   *entry listing* would be cheap and useful and is not a decode of the
   payload; it is nonetheless out of the stated v0 set, so it is a recorded
   v1 candidate rather than a quiet addition.
3. **Headerless positional files are rendered with no column names at all**,
   rather than "with the registered adapter's column names where a label is
   known". The adapter registry lives on disk under `adapters/` and is not
   available to the API process (the API image does not carry it). Serving
   the mapping-spec column labels through the API is the clean fix and is a
   recorded follow-up; guessing was not an option.
4. **The mismatch/missing verdicts return non-2xx** (409/404/410/503) rather
   than a 200 with a field. Stronger than the handoff asked for, and the
   reason is in §2.

#### 11. Still unproven / open

- **Realtime frames are not durably retained.** The largest finding of this
  wave (§1): outside the broker's retention window a GTFS-Realtime record's
  bytes cannot be produced at all. Headway states this honestly, but an FTA
  triennial review asking to see the source records behind a VRH figure from
  eight months ago would get a label and no bytes. Options — landing realtime
  frames in the object store like every other connector, or a much longer
  topic retention — are an **ingestion/DevOps handoff**, out of this wave's
  scope (`services/ingestion/`, `deploy/`).
- **Bulk verification** ("verify this figure's whole evidence chain") is not
  built. It is the natural v1 and a superb demo; on the 1,138-leaf VRH figure
  at ~0.23 s per broker-backed record it needs a batched broker read and a
  progress model, not a loop.
- **Object-store outage** is covered by a test (label degrades to
  `status: "unavailable"` with the reason; the record's identity does not
  depend on the store being up) but was **not** exercised by actually
  stopping MinIO on this box.
- **Decoders for TIDES/DR/telematics envelopes as structured records** (as
  opposed to raw CSV/JSON text) — the handoff's own open question, untouched.
- **Screen-reader pass** was done by role/name/`aria-expanded` assertion and
  a real keyboard walk, not with a live screen reader.
- **Dark theme** was not screenshotted: the CDP capture used for this evidence
  kept returning the light frame after the theme attribute flipped. The new
  CSS introduces **no** hard-coded colours — only the AA-verified tokens and
  `currentColor` — and `npm run check:contrast` passes for both themes, but
  a human should eyeball the dark verdict panels.
- **`Page.captureScreenshot` times out on the lineage GRAPH view** in the
  attached Chrome (the page itself renders at 62 fps with 93 DOM nodes and
  responds to JS). This predates the wave — the SVG is handoff 0007's — but
  it is worth someone's attention, and it is why the screenshots here are all
  of the text view.

#### 12. Screenshots (`docs/images/handoff-0035/`)

| File | What it shows |
| --- | --- |
| `leaf-label-live.png` | A GTFS-Realtime leaf opened: the label, the fingerprint demoted to a footnote, the three actions |
| `verify-match-live.png` | Integrity verified — both fingerprints, 2,702 bytes re-read from the ingest envelope stream |
| `gtfsrt-decoded-live.png` | 25 of 28 entities: real vehicles, routes, trips, coordinates and times from the record's own bytes |
| `verify-mismatch-live.png` | The alarm, on the live store, after a one-character change: `INTEGRITY CHECK FAILED`, both digests, the blocking finding linked |
| `not-retained-live.png` | The honest 410: the bytes aged out of the broker; the trail is unaffected; not a defect |
| `dr-withheld-viewer-live.png` | A viewer on a paratransit record: contents withheld with the reason, Verify still available, Download absent |
| `dr-preview-steward-live.png` | The same record as a data steward: the file's own header and 20 rows, rider coordinates included |

#### 13. Scope

`git status` at hand-off shows only: `services/api/` (README, `app.py`,
`routers/ingest.py` [the two new object-store read seams], `openapi.json`,
`pyproject.toml`, `tests/conftest.py`, plus new `headway_api/raw_payloads.py`,
`headway_api/routers/raw_records.py`, `tests/test_raw_records.py`), `web/`
(README, `api/client.ts`, `api/types.ts`, `copy.ts`, `styles.css`,
`components/LineageGraph.tsx`, `views/LineageView.tsx`,
`test/lineage.test.tsx`, plus new `components/RawRecordInspector.tsx` and
`test/rawRecord.test.tsx`), this handoff, and `docs/images/handoff-0035/`.
Nothing under `services/transform`, `services/ingestion`, `services/calc`,
`services/mcp`, `db/migrations`, `install/`, `deploy/` or `.github/` was
touched. **No commits** — the orchestrator integrates.
