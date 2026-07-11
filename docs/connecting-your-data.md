# Connecting your data

You have run the installer (`install/README.md`) and Headway is up. This
guide is the next step: getting your agency's data flowing in. It is
written for the person who looks after the computers — you do not need to
be a data engineer.

One promise to keep in mind throughout: **Headway never silently drops
data.** Every file and every feed frame you send is kept byte-for-byte,
even when it is malformed — a broken file is stored, marked
`malformed`, and surfaced as a data-quality issue for a person to look at
(see `contracts/README.md`, invariant 2). If something goes wrong, you
will be able to see it, not wonder about it.

## 1. What Headway can ingest today

Honest list — this is what is wired up right now, nothing more:

| Data | How it gets in | What it gives you |
| --- | --- | --- |
| **GTFS schedule (static)** | A web address (URL) to your published `.zip` feed | Your routes and trips in the database. This is the backbone the other data is matched against — vehicle positions get linked to trips, and figures can be broken down by mode. |
| **GTFS-Realtime vehicle positions** | A URL, polled every 30 seconds (configurable) | The live vehicle movement record. This is what lights up **Vehicle Revenue Miles (VRM)**, **Vehicle Revenue Hours (VRH)**, and **Vehicles Operated in Maximum Service (VOMS)**, and it provides the "which trips actually ran" list that the passenger-count math needs. |
| **GTFS-Realtime trip updates** | A URL, polled | **Captured and stored raw only today.** No metric reads it yet — the normalization step currently processes vehicle positions, the static feed, and passenger events. Worth connecting anyway: everything captured now is replayable later. |
| **GTFS-Realtime service alerts** | A URL, polled | Same as trip updates: captured and stored raw, not yet used by any metric. |
| **TIDES passenger events (APC counts)** | A CSV file dropped into a folder, **or** pushed over the network with an API key | Boarding/alighting events. This is what lights up **Unlinked Passenger Trips (UPT)**. |

That is the complete list. There is no direct connection to SQL Server,
Oracle, a data lake, or a vendor database today — see section 4 for the
supported path if that is where your data lives.

A note on the numbers themselves: the figures Headway computes from this
data are previews. The calculation library's own tracker
(`services/calc/REGULATORY_TRACKER.md`) marks every figure not yet
reportable to NTD while known divergences are worked off, and the MR-20
preview report carries a NOT-REPORTABLE banner. Connecting your data now
builds the audited history; it does not put anything on a federal form.

## 2. Real-time feeds (GTFS and GTFS-Realtime)

If you gave the installer your feed URLs, this is already done. To add or
change them later:

1. Open `deploy/compose/.env` in a text editor and set the addresses you
   have (leave the others blank):

   ```
   GTFS_STATIC_URL=https://your-agency.example/gtfs.zip
   GTFS_RT_VEHICLE_POSITIONS_URL=https://your-agency.example/vehiclepositions.pb
   GTFS_RT_TRIP_UPDATES_URL=https://your-agency.example/tripupdates.pb
   GTFS_RT_ALERTS_URL=https://your-agency.example/alerts.pb
   ```

   Two optional knobs live next to them: `POLL_INTERVAL` (how often the
   realtime feeds are polled, default `30s`) and `AGENCY_ID` (only needed
   if one Headway instance ingests feeds from more than one agency).

2. Restart the app services so the collector picks up the change:

   ```sh
   cd deploy/compose
   docker compose --profile app up -d
   ```

**What to expect.** The schedule zip is fetched once each time the
ingestion service starts. The realtime feeds are polled on the interval;
if a poll returns the exact same bytes as the last one, the duplicate is
skipped (and the skip is logged) rather than stored twice. Every fetched
payload is stored as a raw record identified by the SHA-256 hash of its
exact bytes, so re-ingesting the same data is harmless by construction.

**Where to check it worked:**

- **The collector's own log:** `docker compose logs ingestion` — it logs
  every produce and every skip in JSON.
- **The dashboard:** open `http://localhost:8080` (the Headway web app)
  and sign in. Computed figures appear after the calculation run; every
  figure links to "How this number was made."
- **The data-quality queue:** in the web app, or
  `GET /dq/issues` on the API (`http://localhost:8000`). A healthy feed
  shows few or no new issues; a feed with problems shows *named* issues,
  not silence. An empty dashboard plus an empty DQ queue means data is
  not arriving — check the log above.
- **Metrics:** `GET /metrics/values` on the API lists computed values
  once a calculation run has happened.

## 3. Passenger counts (APC) via TIDES

Headway takes passenger counts in the **TIDES** `passenger_events` format
— a plain CSV file. TIDES is an open standard for transit event data; the
authoritative column definitions are the TIDES specification
(`spec/passenger_events.schema.json` in the TIDES-transit/TIDES
repository on GitHub — Headway's importer was verified against spec
commit `d887d42ce081f3fb6155664a3c486101d62ec52b` on 2026-07-10, and the
project rule is to re-verify against the current spec rather than trust
memory).

Your CSV must have at least these six columns (the importer checks the
header):

- `passenger_event_id` — a unique id for each event row
- `service_date` — the service day, e.g. `2026-06-01`
- `event_timestamp` — when it happened, **with the UTC offset** (see the
  timezone warning in section 4)
- `trip_stop_sequence` — the stop's position within the trip
- `event_type` — for counts, use exactly `Passenger boarded` or
  `Passenger alighted` (these are two of the sixteen values the TIDES
  spec allows; spelling and capitalization matter)
- `vehicle_id` — which vehicle

Also strongly recommended: `trip_id_performed` (the GTFS trip that was
actually operated — Headway maps it to the trip id it matched from your
schedule and vehicle positions, which is how counts line up with operated
trips) and `event_count` (how many people; if you leave it blank it is
kept blank, never silently assumed).

A file missing a required column is still stored — marked `malformed` and
flagged, never thrown away — so you can see exactly what arrived and fix
the export.

There are two ways to deliver the file.

### Path A: drop the file in a folder

Copy your CSV, named `passenger_events*.csv` (for example
`passenger_events_2026-06-01.csv`), into the drop folder on the Headway
machine:

```
deploy/compose/tides-drop/
```

The folder is scanned **once, when the ingestion service starts** — there
is no continuous folder watcher yet. After dropping a file, restart the
collector to pick it up:

```sh
cd deploy/compose
docker compose --profile app restart ingestion
```

Handled files are moved into `tides-drop/processed/` so nothing is
ingested twice, and because records are identified by their content hash,
even re-dropping the same file is harmless.

**Label your data honestly — this matters.** The `TIDES_SOURCE` setting
in `deploy/compose/.env` decides the permanent `source` label stamped on
every record from the drop folder:

- For **real APC data from your vehicles**, add this line to `.env`:

  ```
  TIDES_SOURCE=tides
  ```

- For **test or simulated data** (including output of
  `tools/tides-simulator`), use `tides_simulated`. This is the shipped
  default — if you set nothing, drops are labeled simulated, so you
  cannot accidentally pass test data off as real. You *can* make the
  opposite mistake: do not set `TIDES_SOURCE=tides` and then drop test
  files.

The label travels with every record forever and cannot be edited later.
Any figure computed from simulated records is flagged
(`simulated_source_data`) everywhere it appears, including the public
certified-figures endpoint — flags are shown, figures are never quietly
hidden or laundered.

### Path B: push over the network with an API key

For a vendor or an automated system that should send counts directly,
Headway's API accepts an authenticated CSV push. No human account is
shared; instead an administrator issues a **machine API key**.

**Step 1 — the administrator issues a key** (requires the certifying
official role — the account the installer created). The key is scoped to
ingestion only (`ingest:tides`) and **bound to a source label**:

```sh
curl -s -X POST https://headway.agency.example/machine/keys \
  -H "Authorization: Bearer $SESSION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "TIDES simulator", "scopes": ["ingest:tides"],
       "source_label": "tides_simulated"}'
```

For a real vendor feed, use a real `source_label` such as `tides` and a
name identifying the vendor. The full key (it starts with `hwk_`) appears
**once, in this response only** — save it; only a hash is stored. Keys
can be listed and revoked (`GET /machine/keys`,
`DELETE /machine/keys/{id}`); revocation is immediate and audited.

**The binding rule, in plain words:** the key decides how the data is
labeled — forever. Whatever `source_label` the key was issued with is
stamped as the `source` on every record pushed with it; anything the
sender claims in the upload is ignored. So issue *separate keys* for real
and test data: a key labeled `tides_simulated` can never produce records
that look real, and every figure touched by simulated records carries the
simulated flag permanently.

**Step 2 — the vendor pushes the CSV** (same columns as Path A, up to
32 MiB per request; pushes are rate-limited to 60 requests per minute per
key):

```sh
curl -s -X POST https://headway.agency.example/ingest/tides/passenger-events \
  -H "Authorization: Bearer hwk_..." -H 'Content-Type: text/csv' \
  --data-binary @passenger_events_2026-06-01.csv
# -> {"record_id": "<sha256 of the bytes>", "parse_status": "ok"}
```

The response confirms receipt: `record_id` is the permanent
content-addressed identity of that exact file (quote it when asking for
help), and `parse_status` tells you immediately whether the header
checked out. A malformed push still returns 202 and is still stored —
flagged, never dropped. Every push is audit-logged against the key.

**Network note:** on the single-box install, the API listens only on the
machine itself (`127.0.0.1:8000`). For a vendor to reach it from outside,
you need to put it behind your own HTTPS reverse proxy with a certificate
— the compose stack does not expose it publicly or terminate TLS for you
today. Never send API keys over plain HTTP across a network.

## 4. "My data lives in SQL Server / a data lake"

The honest answer: **today Headway has no direct database or data-lake
connector.** It cannot log into SQL Server, Oracle, Snowflake, or a data
lake and pull your APC tables. The supported path is:

> **Export → TIDES CSV → drop the file (Path A) or push it (Path B).**

This is less exotic than it sounds — it is one scheduled query.

### A worked example

Suppose your AVL/APC vendor's database has a table of stop-level counts.
**Column names below are illustrative — adapt them to your schema.** The
shape of the export is:

```sql
-- ILLUSTRATIVE ONLY: your table and column names will differ.
SELECT
    CONCAT(t.trip_key, '-', t.stop_seq, '-B') AS passenger_event_id,
    CONVERT(varchar(10), t.svc_date, 23)      AS service_date,
    -- Must be UTC ISO-8601 WITH the offset, e.g. 2026-06-01T13:05:22Z:
    FORMAT(t.stop_time AT TIME ZONE 'UTC',
           'yyyy-MM-ddTHH:mm:ssZ')             AS event_timestamp,
    t.stop_seq                                 AS trip_stop_sequence,
    'Passenger boarded'                        AS event_type,
    t.vehicle                                  AS vehicle_id,
    t.gtfs_trip_id                             AS trip_id_performed,
    t.ons                                      AS event_count
FROM apc_stop_counts t
WHERE t.svc_date = @export_date AND t.ons > 0
```

and a second, matching query (or a UNION) emitting
`'Passenger alighted'` rows from the `offs` column. Save the result as
`passenger_events_<date>.csv` with a header row.

**Timezone warning — the most common export mistake.** `event_timestamp`
must carry a UTC offset (`...Z` or `...-05:00`). A "naive" timestamp with
no offset is not guessed at: the normalizer records a data-quality
finding and the row is skipped from the canonical data (kept in the raw
file, flagged in the DQ queue — verified behavior of
`services/transform`, which follows the TIDES/Frictionless datetime
rule). If a whole file shows up in the DQ queue with timestamp findings,
this is almost always why.

**Scheduling.** Run the export nightly with whatever scheduler you
already use (SQL Server Agent, cron, Task Scheduler), then deliver it:
copy the file into `deploy/compose/tides-drop/` and restart the ingestion
service (Path A), or `curl` it to the push endpoint with the key (Path B
— no restart needed). A cron sketch for the drop path, run on the Headway
box:

```sh
# ILLUSTRATIVE: fetch last night's export, drop it, rescan.
15 4 * * *  cp /mnt/exports/passenger_events_$(date -d yesterday +\%F).csv \
              /path/to/headway/deploy/compose/tides-drop/ \
            && cd /path/to/headway/deploy/compose \
            && docker compose --profile app restart ingestion
```

Duplicate deliveries are safe: identical bytes get the identical record
id and are not double-counted.

**ROADMAP (not shipped — do not plan around dates).** Headway's
ingestion charter (`.claude/roles/INGESTION_ENGINEER.md`) plans a fleet
of source adapters beyond today's connectors, including CAD/AVL (vendor
APIs and scheduled SFTP/S3 file drops), APC vendor formats, farebox/AFC,
and J1939 vehicle telematics. None of these exist yet, and no dated
commitment exists for a native database or data-lake connector. What
*does* exist today is the integration surface they will all use: the
versioned wire contract in `contracts/` (the raw-record envelope and
topic registry). A vendor or an in-house developer can build a connector
against that contract now, without waiting for Headway to ship one.

## 5. How to know it's working

Three layers, from "bytes arrived" to "this number is traceable":

1. **Raw records land — and nothing is ever dropped.** Every delivery is
   stored with its content hash before anything else happens, including
   malformed ones (`parse_status: "malformed"` plus a stated reason).
   This is Headway's fail-loudly promise: bad data is kept and flagged,
   never discarded, so a gap can never be silent. The ingestion log
   (`docker compose logs ingestion`) and, for pushes, the 202 response
   with its `record_id` are your receipts.

2. **The data-quality queue is the health surface.** Open the DQ queue in
   the web app (`http://localhost:8080`) or `GET /dq/issues`. Every
   problem the pipeline finds — a malformed file, a naive timestamp, a
   telemetry gap, an unknown event type — becomes a named issue with a
   severity, assigned to a person to resolve, with the resolution
   audited. Blocking issues prevent certification until resolved. **A
   quiet DQ queue with data flowing is health; a quiet DQ queue with an
   empty dashboard means nothing is arriving.**

3. **The lineage walk is the proof.** Pick any computed figure in the web
   app and open "How this number was made," or call
   `GET /metrics/values/{id}/lineage`. It walks the actual recorded
   chain: the figure, the exact versioned calculation that produced it,
   down to the content-addressed raw record ids of the files and feed
   frames you sent. If your data is in the platform, it is in that walk.
   (A figure with no lineage is treated as an error by the API itself —
   it will not pretend.)

## 6. Getting help / what to send us

When you open an issue, include identifiers — never the data itself:

- **Record ids** — the 64-character `record_id` from a push response or
  the ingestion log. It identifies the exact bytes without containing
  them.
- **DQ issue ids** — from the DQ queue or `GET /dq/issues`.
- What you expected, what you saw, and the relevant service log
  (`docker compose logs ingestion`, `... transform`, `... api`).
- For install problems, `install/install.log` (it contains no passwords).

**Never attach raw passenger-event CSVs or other rider-level data** to a
public issue. The record id is enough for anyone with access to your
system to find the exact record; nobody outside needs the contents.

---

*Drafting note: AI-assisted draft, verified against the repository on
2026-07-11 (sources: `deploy/compose/compose.yaml` and `.env.example`,
`services/ingestion/README.md` and `connectors/tides/tides.go`,
`services/transform/README.md`, `services/api/README.md`,
`contracts/topics.v0.md` and `raw-record-envelope.v0.schema.json`,
`services/calc/README.md`, `tools/tides-simulator/README.md`. TIDES
column requirements per the TIDES spec commit cited in section 3;
pending human review before publication to the docs site. The end-to-end
TIDES flow and the API's live-stack run are marked PENDING live
verification in their own READMEs; the behaviors described here are the
coded and unit-tested contracts those verifications will exercise.*
