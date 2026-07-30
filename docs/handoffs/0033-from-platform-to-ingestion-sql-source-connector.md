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
(appended by the implementing agent)
