# Handoff: platform → ingestion — Generic SQL-source connector (agency-supplied view)

## Context
First partner agency wants APC ingestion **more frequent than nightly**; their fixed-route
APC lives in an on-prem SQL Server warehouse. Design ratified in ROADMAP ("framing
corrected 2026-07-29"): Headway ships a **generic** connector that reads a **view or
query the agency supplies in configuration** — vendor table/column names never enter
this repository. The agency-side prereqs (read-only `headway_ro` login, `vw_headway_apc`
view, firewall path) were handed to their DBA 2026-07-29; build so the connector is
ready when that ticket clears.

## Design (binding)
1. **Go connector** (`services/ingestion/connectors/sqlsource/`), driver
   `github.com/microsoft/go-mssqldb` (verify BSD-3 against the license gate). SQL Server
   first; the config shape must not preclude Postgres/Oracle drivers later.
2. **Config, all from env, fail-closed:** DSN (`SQLSOURCE_DSN`, never logged — including
   in errors), the query/view name, a **keyset cursor column** (e.g.
   `VehicleLocationAPCKey` — monotonic, agency-declared), poll interval, batch cap, and
   `SQLSOURCE_ADAPTER_LABEL` (must name a registered adapter — the 0015 fail-closed
   rule). Missing anything = refuse to start with the plain-language pattern.
3. **Incremental keyset polling:** each poll reads `WHERE cursor > high_water ORDER BY
   cursor` up to the cap; the high-water mark persists so restarts never re-read history
   (where it persists is your call — record it; content addressing makes accidental
   replay harmless anyway, prove it).
4. **Reuse the proven pipeline, don't fork it:** each polled batch is rendered to the
   registered adapter's declared positional-CSV shape and lands exactly like a dropped
   file — store-before-produce to `raw.vendor.files`, content-addressed, then the
   existing adapter runtime + (0031) trip resolution take over untouched. One pipeline,
   two intakes. Record the column-order contract between config and adapter spec, and
   refuse on width mismatch (the wrong_width precedent).
5. **Minimization applies** (ADR-0013): the connector selects only the columns the
   adapter declares — `SELECT *` is refused in config validation.
6. **Honest scope:** read-only queries only (no DML, statement-timeout set); no schema
   discovery; no Postgres/Oracle drivers yet.

## Outputs
Connector + tests (`go test`/`vet`; fake-driver unit tests for keyset/backoff/refusals;
integration against a DISPOSABLE `mcr.microsoft.com/mssql/server` container via
`sg docker -c` if it runs on this box — if not, say so and pin by fakes); docs:
`docs/connecting-your-data.md` §"direct database" (plain words, the view-is-the-contract
posture, the exact env lines), compose wiring env passthrough (off by default);
README verification section stating no agency server was contacted; evidence here. No
commits — the orchestrator integrates.

## Open Questions
- Postgres/Snowflake drivers; per-source schedules; TLS cert pinning guidance for
  agency DBAs; whether the high-water mark belongs in app.settings for visibility.

## Outputs — evidence

**2026-07-30, Ingestion Engineer. Contract accepted; built as designed with the
deviations recorded below. No commits — the orchestrator integrates.**

### What was built

- `services/ingestion/connectors/sqlsource/` — the connector (`sqlsource.go`),
  fake `database/sql` driver + 30 unit tests (`fakedb_test.go`,
  `sqlsource_test.go`), and a container-gated integration test
  (`sqlsource_integration_test.go`).
- `services/ingestion/cmd/headway-ingest/main.go` — `SQLSOURCE_*` env wiring,
  `SQLSOURCE_ENABLED` on-switch (the Samsara precedent: the secret is never the
  on-switch, so a missing DSN is a loud refusal).
- `services/ingestion/connectors/vendorfile/objectstore.go` — one added test
  helper (`FakeStore.Keys`); nothing else in the proven pipeline was touched.
- `deploy/compose/compose.yaml` — env passthrough, off by default;
  `deploy/compose/sqlsource-state/` state-dir placeholder (tracked `.gitignore`,
  the drop-dir convention).
- `docs/connecting-your-data.md` — new §5 subsection "Direct from SQL Server:
  the view is the contract" with the exact env lines.
- `services/ingestion/README.md` — layout row, config table, license table,
  dated verification section including the no-agency-server statement.
- `services/ingestion/go.mod` / `go.sum` — `github.com/microsoft/go-mssqldb`
  v1.10.0 (+ 3 transitive: golang-sql/civil, golang-sql/sqlexp,
  shopspring/decimal).

### Design decisions within the binding design (each recorded, none silent)

1. **Config shape: `SQLSOURCE_VIEW` + `SQLSOURCE_COLUMNS`, not free-form SQL.**
   The connector builds its one SELECT itself from a validated view name (1–3
   dot-separated plain identifiers, bracket-quoted) and the ordered column
   list. This makes SELECT * structurally refusable (§5), makes injection via
   config impossible, and keeps the connector incapable of DML by construction
   (§6). Query logic belongs inside the agency's view — the view is the
   contract.
2. **Column-order contract (§4), enforced at both ends:** SQLSOURCE_COLUMNS
   is documented as EXACTLY the adapter's `source_format.csv.columns` in
   order; at poll time the result set's column names/order/count must equal
   the configured list or the batch is refused whole (nothing landed, mark not
   advanced, message names the first disagreeing position and cites the
   wrong_width rule); downstream the adapter runtime still quarantines
   wrong-width rows (`services/transform/tests/test_adapters.py::
   test_tripspark_wrong_width_export_quarantines_every_row`, untouched).
3. **High-water mark: atomic JSON state file** under `SQLSOURCE_STATE_DIR`
   (`sqlsource-<label>.json`, temp+rename), NOT `app.settings` — keeps the
   connector free of any Postgres dependency (the ingestion service has none
   today). The file records view + cursor column and is refused if reused
   under a different contract. Mark advances only AFTER land + produce
   (at-least-once). The open question "does it belong in app.settings for
   visibility" stays open — moving it later is a state-file migration, not a
   schema change.
4. **Replay harmless, proved:** `TestDeletedStateReplayIsIdempotentByContent-
   Address` deletes the state file, re-polls the same rows, and asserts the
   identical `record_id` (identical rendered bytes → same content address).
   Row-level idempotency under different batch boundaries is the adapter
   engine's deterministic natural keys ("redelivery writes nothing new",
   contracts/adapter-mapping.v0.md) — recorded here, not re-proved, since that
   side is untouched.
5. **v0 cursor is INTEGER-only** (int64), refused otherwise with a
   plain-language message. A serialized datetime cursor losing precision could
   silently skip or re-read rows; refusing is the honest scope. NULL cursors
   refuse the batch (a `WHERE cursor > x` would otherwise silently exclude
   them forever — fail loudly, Guardrail 7). A cursor tie at a FULL batch
   boundary is refused (advancing could skip tied rows); mid-batch ties in a
   short batch are fine and tested.
6. **Datetime/float/decimal/binary cells are refused, never formatted**, with
   the message naming the column and the CAST-in-the-view fix. Headway
   choosing a date format would be silent normalization at the ingest
   boundary. Deterministic renderings: NULL → empty, int64 → decimal, bit →
   1/0, strings/varbinary verbatim. Verified against the real driver in the
   integration test.
7. **Pipeline reuse is literal:** sqlsource imports the vendorfile connector's
   `Topic` (`raw.vendor.files`), `ObjectKey` (`raw/vendor/<record_id>.csv`),
   `ObjectStore`/`MinioStore`, and content type. parse_status is always `ok`
   (the vendorfile rule — only the registered mapping spec knows the format);
   the 0015 fail-closed unregistered-label refusal and per-row quarantine
   happen in the transform runtime, untouched. The structural `sim:`-marker
   refusal is enforced at this intake too (a marked cell under a non-
   `_simulated` label refuses the batch before anything is landed).
8. **Secrets:** the Poller never holds the DSN — it receives an open `*sql.DB`
   — so no connector log line can contain it. `OpenDB` withholds both the DSN
   value and the driver's parse detail from its error (driver parse errors can
   echo connection-string fragments). Test asserts a password planted in a
   malformed DSN never appears in the error.

### Verification (all run 2026-07-30 on this branch, uncommitted)

`go build ./... && go vet ./... && go test ./... -count=1`
(host go1.22.2, toolchain auto-selected go1.25.12; go directive 1.25.0→1.25.7
forced by go-mssqldb):

```
ok  .../connectors/dr         0.018s
ok  .../connectors/gtfsrt     0.010s
ok  .../connectors/gtfsstatic 0.012s
ok  .../connectors/samsara    0.021s
ok  .../connectors/sqlsource  0.024s
ok  .../connectors/tides      0.022s
ok  .../connectors/vendorfile 0.029s
ok  .../internal/envelope     0.002s
```

**108 passing tests module-wide** (was 73), 30 new in sqlsource: rendering/
landing/envelope correctness against the tripspark 18-column shape with the
exact CSV asserted byte-for-byte; restart-resume with the keyset predicate
and `@p1` parameter asserted; deleted-state replay idempotence; batch-cap
pagination (2+2+1) with per-batch cursor parameters; column-order mismatch
refusal; NULL / non-integer cursor refusals; unformattable-type refusal
naming column + fix; boundary-tie refusal and mid-batch-tie acceptance; sim-
marker refusal + `_simulated` acceptance; produce-failure and store-failure
not advancing the mark (and at-least-once redelivery after recovery); state-
contract mismatch refusal; a 12-case Check refusal matrix (each message names
its env var; includes SELECT-* → ADR-0013 and injection attempts in view/
column names); DSN-secrecy; periodic Run + clean cancel.

**License gate (binding check from §1): PASS.**
`python3 scripts/license_gate.py --ecosystem go` → **32/32 dependencies
conform**; `github.com/microsoft/go-mssqldb  BSD-3-Clause  PASS` (the
handoff's assumption held), civil Apache-2.0, sqlexp BSD-3-Clause, decimal
MIT. LICENSE files also read directly in the module cache. go-licenses
confirms the Azure-AD auth subpackages are not in the import graph — no
Azure SDK code links into the build. (Gate note: with GOTOOLCHAIN=auto the
documented GOROOT export from the script header is needed, exactly as the
script documents.)

**Integration: the disposable container RAN — this is real-driver evidence,
not fakes-only.** `sg docker -c "docker run -d --name headway-0033-mssql -e
ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=<generated> -p 127.0.0.1:21433:1433
mcr.microsoft.com/mssql/server:2022-latest"` (image digest sha256:ba4c8329…,
localhost-only port, container and password removed after the run; the live
Compose project was never touched). `SQLSOURCE_IT_DSN=… go test -run
Integration -v` → `--- PASS: TestIntegrationKeysetPollAgainstRealSQLServer
(0.11s)`: an agency-shaped view (warehouse columns aliased to the 18 adapter
positions, `CONVERT(varchar(19), event_time, 126)` for the datetime); 5
seeded rows through a 2-row cap → 3 batches with row 1 asserted
byte-for-byte; idle poll lands nothing; 2 late rows picked up by keyset
resume only; a restarted poller resumes from the persisted mark; a
deliberately wrong view exposing raw `datetime2` refused naming
`EventDateISO` and the CAST fix. Fixture rows ran under
`tripspark_streets_simulated` (synthetic data, labeled as such — binding
0005 rule).

**NO AGENCY DATABASE SERVER WAS CONTACTED.** Nothing here has spoken to any
system outside this machine except the Microsoft container registry and the
Go module proxy.

**Scoped `git status --short`** (all changes inside the handoff's scope):

```
 M deploy/compose/compose.yaml
 M docs/connecting-your-data.md
 M services/ingestion/README.md
 M services/ingestion/cmd/headway-ingest/main.go
 M services/ingestion/connectors/vendorfile/objectstore.go
 M services/ingestion/go.mod
 M services/ingestion/go.sum
?? deploy/compose/sqlsource-state/
?? services/ingestion/connectors/sqlsource/
```

### Deviations / notes for the orchestrator

1. **docs/connecting-your-data.md:** besides the one new §5 subsection, three
   sentences that flatly said "no direct database connector exists" (§1's
   closing note, §5's opening, §5's ROADMAP paragraph) were minimally
   reconciled — leaving them false would have violated the honesty posture
   the doc leads with. No other restructuring.
2. **go.mod `go` directive moved 1.25.0 → 1.25.7** (go-mssqldb v1.10.0
   requires ≥1.25.7). CI installs the go.mod version natively; local hosts on
   GOTOOLCHAIN=auto are unaffected.
3. `TestPollOnceRendersLandsAndProduces` asserts the generated T-SQL text
   verbatim — if the dialect rendering ever changes, that test is the tripwire.
4. Not done, deliberately (honest scope §6): Postgres/Oracle drivers, schema
   discovery, non-integer cursors, per-source schedules, TLS cert-pinning
   guidance (open questions stand).

### To re-verify when the agency's DBA ticket clears (against their server)

- The firewall path and `encrypt=true` TLS through it (and whether their SQL
  Server's certificate needs `trustservercertificate`/CA guidance — feeds the
  open cert-pinning question).
- `headway_ro` is genuinely read-only (attempt an INSERT with those
  credentials once, expect a permission error) and can see ONLY the view.
- The real `vw_headway_apc` column list matches the registered adapter's 18
  positions in order, dates pre-cast to `varchar` in the sample's exact
  format, and the declared cursor column is a non-null unique growing integer
  (`VehicleLocationAPCKey` was the working assumption).
- `nvarchar` collation/encoding of real stop/route names survives the
  UTF-8 CSV rendering byte-for-byte into the adapter.
- Poll interval + batch cap reviewed with their DBA against real warehouse
  load; then the first live end-to-end walk: view → raw.vendor.files →
  adapter runtime → canonical rows with lineage to the landed batch.
