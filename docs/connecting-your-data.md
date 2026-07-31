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
| **Fleet telematics (Samsara)** | A read-only API token, polled once a day | Measured vehicle movement: how far each vehicle went and how long its engine ran, per day, with the measurement method recorded. **This is NOT revenue miles or revenue hours** and no figure is computed from it. Vehicle-level only — no driver data of any kind. See section 4. |

That is the complete list, with one recent addition: Headway can now also
read **directly from a SQL Server view your DBA creates** (section 5).
There is still no connection to Oracle, Snowflake, or a data lake — see
section 5 for the supported paths if that is where your data lives.

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
  timezone warning in section 5)
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

### Path C: your vendor system's own export files (adapters)

If Headway has an **adapter** for your vendor's native export format, you
do not need to reshape anything — drop the file your system already
produces. Today's adapters: **TripSpark Streets APC** (label
`tripspark_streets` — the headerless positional CSV its data warehouse
exports). Two lines in `deploy/compose/.env` switch the path on:

```
VENDOR_DROP_DIR=/data/vendor-drop
VENDOR_SOURCE=tripspark_streets
```

Apply the change once after setting them — from `deploy/compose`:

```sh
docker compose --profile app up -d ingestion
```

(`up -d`, not `restart`: a plain restart reuses the container's old
settings and would silently ignore your new `.env` lines. `up -d`
recreates the container with the new values. This applies to ANY `.env`
change, including feed URLs.)
From then on, files copied into `deploy/compose/vendor-drop/` are picked
up **automatically within about half a minute** — no restart per file.
Handled files move to `vendor-drop/processed/`; identical bytes are never
double-counted. Every record carries dual lineage: the raw vendor file
AND the exact adapter mapping version that interpreted it.

The label is fail-closed in both directions: an unregistered
`VENDOR_SOURCE` is refused outright, and synthetic/test files must never
be dropped under a real vendor label — test data belongs in Path A with
the `tides_simulated` label, where every figure it touches is flagged.

#### Matching your counts to your schedule ("trip resolution")

Your APC system and your schedule usually name the same trip differently:
the export might say `12 - 12WD - 21:30` (the way your schedulers talk)
while your GTFS feed's trip id is a long random-looking string. Until the
two are matched, passenger counts cannot be attributed to scheduled trips
— and ridership numbers that depend on that attribution stay blocked.

Headway matches them using a small per-agency configuration file next to
the adapter (`resolution.v0.yaml`): how your trip names are built, which
schedule fields each part corresponds to, what your direction codes mean,
and how trips after midnight are dated. Nothing is guessed — one setting
in that file (which of your direction values is which GTFS direction)
**needs your confirmation before matching starts**, and until you confirm
it Headway says so plainly in the data-quality queue instead of flipping
a coin. A wrong direction guess would put counts on the wrong trips with
nothing visibly broken, which is worse than waiting.

Once it runs, every row gets exactly one of three outcomes, and you see
the tallies per file in the data-quality queue:

- **Matched** — exactly one scheduled trip fits. The row is attributed to
  it, and the trip name your system used is kept alongside forever, so
  you can always trace a number back to your own records.
- **More than one fits** — Headway does not pick. The finding names the
  candidate trips (typically a handful of schedule variants sharing a
  route, start time and direction) so a human can decide.
- **No trip fits** — the finding shows how the trip name was read and
  what was searched: wrong service day, a trip not in the loaded
  schedule, a retired stop code, an after-midnight trip dated the other
  way. The counts still land either way — nothing is dropped — they are
  just not attributed until the cause is fixed.

If a delivery shows "0 of 1,200 matched", the usual causes are: the
loaded schedule feed is not the one that was in effect for those dates,
or the direction confirmation is still pending. The finding text says
which.

#### Naming your blocks the way your run board does

Some scheduling systems export a GTFS feed whose `block_id` is a long
random-looking string, while your dispatchers call the same block
something like `225-4`. Headway never invents a name it does not have, so
findings over such a feed can only show the long id — **unless you supply
the mapping**. If your system can export a trip→block list (two columns:
the trip name in your own format, the block name your dispatchers use),
Headway derives which feed block each name belongs to using the same
trip-name reading as the matching above, loads it as reference data, and
from then on new findings that group trips by block lead with your block
names — the long id stays one click away for anyone tracing a record.
Rows the derivation cannot place are counted and reported, never guessed.
See `tools/block-labels/README.md` for how to run it. (If your vendor can
simply put the operational block name in the feed's `block_id`, that is
still the better fix — it helps every consumer of your feed, not just
Headway.)

> **Buying or replacing a system right now?** The cheapest time to
> guarantee you can get your data out is before you sign. See
> [`docs/procurement-data-requirements.md`](procurement-data-requirements.md)
> — five questions for every bidder and the contract clauses worth having,
> vendor-neutral.

## 4. Vanpool and fleet telematics (Samsara)

If your vanpool (or any part of your fleet) runs on Samsara, Headway can
pull each vehicle's daily movement straight from it — no more collecting
odometer sheets by hand.

### What this actually gives you — and what it does not

**Read this before you connect anything.** What Headway collects here is
**how far each vehicle moved and how long its engine ran**, day by day.

That is **not** revenue miles and **not** revenue hours. An odometer reading
goes up for everything the van did: carrying passengers, driving to and from
the garage, the trip to the tyre shop, the driver's lunch run — and on a
vanpool van kept at a participant's home, personal use too. An engine-hour
meter counts the engine running, including sitting idling in a car park.

So Headway **does not compute anything from this data**. Not a mile, not an
hour, not an NTD figure. It records what the vehicles measured, records
*how* each measurement was taken, records where the measurement is blind,
and stops there. Turning measured movement into reportable vanpool figures
needs the FTA's own vanpool rules written into Headway's regulatory tracker
first, plus a way for you to declare which vehicle-days were actually
revenue service. That is deliberate future work, not something quietly
happening in the background.

What you get today is the **audited history**: every day's measurement, kept
byte-for-byte from the source, ready for the day the reportable figures are
built on top of it.

### What Headway collects — and what it deliberately does not

**Telematics is employee-monitoring data.** A van's movement history is, in
practice, a record of what a person did with their day. Headway therefore
collects the least it can and still do the job, and this table is the whole
answer — one page your HR lead or your attorney can read.

| | |
| --- | --- |
| **What Headway asks Samsara for** | Five vehicle measurements only: three ways of measuring **distance** and two ways of measuring **engine running time**. Each is a number and a timestamp, per vehicle. |
| **What it keeps** | The vehicle's id and name, and for each reading its time and its value. That is the complete list. |
| **What it never asks for** | Vehicle GPS locations, ID-card scans, fault codes, fuel, speed, engine on/off events — or any other Samsara data series. |
| **Driver data — never collected** | No driver names or ids, **no hours-of-service or ELD duty logs**, no driver safety scores, no harsh-braking or harsh-acceleration events, no dashcam or video references. None of it is ingested, and **there is no setting that turns any of it on.** |
| **Removed before anything is saved** | If Samsara sends anything else in the same response — including its `externalIds` field, which Samsara's own documentation shows holding a **payroll id** — Headway strips it out **before writing anything to disk**. It is never stored "just in case". Headway records *which* fields it removed, never their contents. |
| **Permission you grant** | **Read Vehicle Statistics**, and nothing else. No permission to change anything in Samsara, and no permission that would give Headway driver-behaviour or compliance data. |

If a future version of Headway ever needs driver-level data, it will have to
be switched on deliberately, with a warning attached, because collecting it
may involve your collective-bargaining agreements, state employee-privacy
law, and your own data-classification rules. Today there is nothing to
switch on.

**Being straight with you about one thing:** even with no driver name
anywhere in it, this data is **not anonymous**. Daily distance and engine
hours per vehicle, put next to vehicle assignments or run sheets you already
keep, can show who was driving and roughly what they did. That is true of
telematics data generally, not a quirk of Headway. Treat these records as
employee records.

### The three ways a distance can be measured — kept separate on purpose

Samsara can report a vehicle's distance three different ways, and they are
**not** interchangeable:

| How it was measured | What it really is |
| --- | --- |
| **Engine-computer odometer** | The van's own odometer, read off its diagnostic port. The number on the dashboard. Not every vehicle supports it. |
| **GPS odometer** | An odometer Samsara maintains from GPS travel — but it only works once **somebody types in a starting odometer reading**. Without that, it does not update. |
| **GPS distance** | Distance the *tracking device* has accumulated since it was installed. It belongs to the device, not the van: swap the device and the count starts over. |

Headway stores each of these as its own separate record, labelled with how
it was measured. If a van has no engine-computer odometer, Headway says so
in the data-quality queue — it **never** quietly puts the GPS number in that
column instead. If two methods disagree, you see both figures, not an
average.

Two more things Headway records rather than smooths over:

- **Gaps.** Each record says the longest stretch between two readings that
  day. If a van moved 40 miles and there is a six-hour hole in the middle,
  you are told; Headway never spreads the miles across the gap.
- **Counters going backwards.** A running total cannot decrease, so if it
  does (usually a replaced tracking device), Headway keeps both readings,
  leaves the distance blank, and raises an issue. It never invents a
  plausible number.

### What to ask your Samsara administrator for

One **read-only API token**, with **one** permission:

> **Read Vehicle Statistics** (under the *Vehicles* category)

That is the whole ask. Headway requests **no permission to change anything**
in Samsara, and no access to driver hours-of-service or compliance records.

Two things worth doing while you are there:

1. **Tag your vanpool vehicles** and use Samsara's *Tag Access* when
   creating the token. The token then cannot see any vehicle outside that
   tag — the safest possible arrangement.
2. **Name the token for Headway specifically**, so it can be revoked on its
   own without breaking other integrations.

Copy the token when it is shown — Samsara will not show it again.

### Turning it on

1. Add these to `deploy/compose/.env`:

   ```
   SAMSARA_ENABLED=true
   SAMSARA_API_TOKEN=<the read-only token>
   SAMSARA_SOURCE=samsara
   SAMSARA_SERVICE_DAY_TZ=America/New_York
   HEADWAY_TELEMATICS_SERVICE_DAY_TZ=America/New_York
   ```

   - `SAMSARA_SOURCE` must be `samsara` for a real account. Use
     `samsara_simulated` **only** for test data — that label follows the
     records forever, so simulated data can never be mistaken for real.
   - The two timezone settings must be **identical**. A "service day" is a
     local calendar day, so Headway needs to be told which timezone yours
     is; it will never guess one. Optional extras:
     `SAMSARA_TAG_IDS` / `SAMSARA_VEHICLE_IDS` to poll only part of the
     fleet, and `SAMSARA_ENGINE_TIME=false` to skip engine hours.

2. Bring the services up so they pick up the change (`.env` changes need
   `up -d`, not `restart`):

   ```sh
   cd deploy/compose
   docker compose up -d ingestion transform
   ```

3. Watch the first cycle:

   ```sh
   docker compose logs -f ingestion | grep samsara
   ```

   You should see `samsara telematics poller started`, then one
   `telematics page landed and produced` line per page of data.

**If a setting is missing, the connector refuses to start and tells you
which one** — a missing token, a missing source label or a missing timezone
is a loud failure, never a connector that silently does nothing. Your token
never appears in a log line.

By default Headway polls yesterday and the two days before it, once every
six hours. Yesterday rather than today because a day is not finished until
it ends, and vehicles upload their data late; re-reading the same days costs
nothing because identical data is recognised and never counted twice.

## 5. "My data lives in SQL Server / a data lake"

Two supported paths now. **SQL Server:** Headway can read directly from a
view your DBA creates — see "Direct from SQL Server" below. **Oracle,
Snowflake, a data lake, or anything else:** no direct connector yet; the
supported path is:

> **Export → TIDES CSV → drop the file (Path A) or push it (Path B).**

This is less exotic than it sounds — it is one scheduled query. The export
path also stays fully supported for SQL Server, and it is the right choice
when there is no DBA to create a view: the direct connector below is for
agencies that already run a reporting warehouse.

### Direct from SQL Server: the view is the contract

Headway ships a **generic** database connector. Generic means: Headway
does not know, and will never contain, your vendor's table or column
names. Instead, **your DBA creates a view** — a saved, named query — that
presents the data in the shape Headway's adapter for your vendor format
declares, and Headway reads *only* that view, with a login that can read
*only* that view. The view is the contract between your database and
Headway: when your vendor upgrades and renames its internals, your DBA
edits the view, and nothing on the Headway side changes.

What your DBA sets up (these are the same prerequisites your Headway
contact hands over as a ticket):

1. **A read-only login** for Headway (e.g. `headway_ro`) with SELECT
   permission on the view below and nothing else.
2. **A view** (e.g. `dbo.vw_headway_apc`) whose columns are exactly the
   columns Headway's adapter for your vendor format declares, in that
   order — for the TripSpark Streets APC adapter that is the 18 columns
   in `adapters/tripspark/streets/mapping.v0.yaml`. Two rules that save
   debugging later: **cast dates and times to text in the view**, in
   exactly the format your vendor's export uses (Headway refuses to
   invent a date format — a `datetime` column left uncast is reported as
   an error naming the column), and make sure the **key column** (next
   item) is a whole number that only ever grows.
3. **A cursor column**: one of the view's columns must be a unique,
   ever-increasing whole-number key (warehouses almost always have one).
   Headway remembers the highest key it has read and asks only for newer
   rows — that is what makes frequent polling cheap.
4. **A firewall path** from the Headway machine to the database port.

Then, on the Headway side, in `deploy/compose/.env` (the connector is off
until you set these; if one is missing it refuses to start and tells you
which one):

```sh
SQLSOURCE_ENABLED=true
# The read-only login. Never logged, never shown in an error.
SQLSOURCE_DSN='sqlserver://headway_ro:THE_PASSWORD@warehouse-host:1433?database=WAREHOUSE&encrypt=true'
SQLSOURCE_VIEW=dbo.vw_headway_apc
# EXACTLY the adapter's declared columns, in the adapter's order:
SQLSOURCE_COLUMNS=VehicleLocationAPCKey,VehicleName,TotalCount,BoardCount,AlightCount,UnmodifiedAlightCount,APCSource,IsTripper,IsDetour,TripName,RouteName,RouteShortName,PatternName,StopName,StopCode,PatternPointRank,DirectionKey,EventDateISO
SQLSOURCE_CURSOR_COLUMN=VehicleLocationAPCKey
SQLSOURCE_ADAPTER_LABEL=tripspark_streets
# Optional: how often to ask for new rows (default 5m — this is the
# "more often than nightly" knob), and the rows-per-batch cap.
SQLSOURCE_POLL_INTERVAL=5m
```

then `docker compose --profile app up -d` (a `.env` change needs `up -d`,
not `restart` — see `docs/updating.md`).

What Headway does with it, in plain words: every few minutes it asks the
view for rows newer than the last one it has seen, writes them down as a
file — byte-for-byte the same pipeline as a dropped export file, with the
same content-addressed receipts, data-quality queue, and lineage walk —
and remembers where it stopped (under `deploy/compose/sqlsource-state/`,
so restarts pick up where they left off, never re-reading history and
never skipping any). Reading the same rows twice is harmless: identical
data is recognised and never counted twice.

What Headway will *not* do, by construction: it never writes to your
database (the connector is only capable of one generated SELECT, and the
read-only login is your enforcement of that); it never reads columns you
did not list (`SELECT *` is refused outright — a column Headway was not
told about is never read, let alone stored; see ADR-0013); and the
connection string with its password is never written to a log, not even
in error messages.

If the columns do not line up — wrong names, wrong order, wrong count —
the whole batch is refused with a message saying exactly which position
disagrees, and nothing is stored until it is fixed. That is deliberate:
a guessed column mapping would be worse than a loud stop.

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
and J1939 vehicle telematics. None of these exist yet, and beyond the SQL
Server connector above, no dated commitment exists for other native
database or data-lake connectors (Oracle, Snowflake, …). What
*does* exist today is the integration surface they will all use: the
versioned wire contract in `contracts/` (the raw-record envelope and
topic registry). A vendor or an in-house developer can build a connector
against that contract now, without waiting for Headway to ship one.

## 6. How to know it's working

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

## 7. Getting help / what to send us

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
2026-07-11, with the fleet-telematics section (4) added and verified
2026-07-29 (sources for that section: `services/ingestion/connectors/samsara/`
and its README, `contracts/fleet-telematics.v0.md`,
`db/migrations/0034_vehicle_telematics_days.sql`,
`services/transform/headway_transform/telematics_vehicle_days.py`, and
Samsara's own published OpenAPI document, `info.version` 2025-10-23,
retrieved 2026-07-29 — no live Samsara account was contacted; the Samsara
permission names and behaviours quoted are the vendor's published wording).
Original sources: `deploy/compose/compose.yaml` and `.env.example`,
`services/ingestion/README.md` and `connectors/tides/tides.go`,
`services/transform/README.md`, `services/api/README.md`,
`contracts/topics.v0.md` and `raw-record-envelope.v0.schema.json`,
`services/calc/README.md`, `tools/tides-simulator/README.md`. TIDES
column requirements per the TIDES spec commit cited in section 3;
pending human review before publication to the docs site. The end-to-end
TIDES flow and the API's live-stack run are marked PENDING live
verification in their own READMEs; the behaviors described here are the
coded and unit-tested contracts those verifications will exercise.*
