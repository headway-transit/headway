# Handoff: platform-architect → ingestion, transform — Vendor adapter framework v0 (TripSpark Streets first; mapping BLOCKED on sample)

## Context
Direct vendor integrations are the platform's biggest adoption lever (project direction, 2026-07-13): agencies' operational data lives in Trapeze/TripSpark, Swiftly, Clever Devices, Ecolane, Spare, etc. The first real flow is a partner agency: MDT manual passenger counts → TripSpark → files pushed to an agency storage server (consumed today by Streets reports). ADR-0006 rule: Headway core speaks ONLY open contracts (TIDES passenger_events, demand_response_trip, GTFS/GTFS-RT). Vendors get ADAPTERS — declarative mappings from their export formats onto those contracts — never bespoke pipeline forks. The hardened file-drop machinery (stability guard, size caps, fail-closed source labels, per-row quarantine) is the intake; adapters are a mapping layer in front of it.

## Design (binding)
1. **Mapping-spec format** (`adapters/<vendor>/<product>/mapping.v0.yaml` + prose doc): source format declaration (CSV dialect/fixed-width/XML), field → contract-field mappings with type coercions, constant/derived fields (e.g. mode, TOS), unit conversions, timezone declaration (NEVER guessed), row-filter predicates, and REQUIRED provenance block: vendor, product, export name/version the spec was verified against, verification date, and sample-fixture reference. A spec without a verified sample fixture cannot be registered — field semantics never from memory or vendor docs alone.
2. **Adapter runtime** (Go or transform-side Python — implementer chooses per where the contract lands; document the choice): reads the mapping spec, transforms vendor files into contract-conformant records, runs the CONTRACT's validation, quarantines per-row per the hardening patterns, stamps envelope source as `<vendor>_<product>` (registered label; the fail-closed label rules apply). Content addressing on the ORIGINAL vendor bytes (raw record = what the vendor pushed; the mapped record carries lineage to it).
3. **Validation harness**: `adapters/validate` — given a mapping spec + fixture files, prove: every mapped record passes contract validation; every fixture row is either mapped or explicitly quarantined with a reason; round-trip determinism. CI-runnable; a registered adapter without green harness fixtures fails the build.
4. **First adapter: TripSpark Streets (BLOCKED — needs the partner agency's sample)**: manual MDT passenger counts → TIDES passenger_events (or ride-check measurements for the sampling module — decide from the sample's granularity). Everything about its fields waits for the real export; the framework ships with a synthetic reference adapter (`adapters/_reference/`) exercising every mapping-spec feature as the harness's own fixture.
5. **Registry + docs**: `adapters/README.md` — how the community adds a vendor (spec + fixtures + harness green + provenance block); explicit note that adapters map an agency's OWN exports (no reverse-engineering of licensed software; agencies own their data).

## Outputs
Framework + reference adapter + harness + registry docs, suites green, evidence here. TripSpark mapping lands as a follow-up the day a sample export exists.

## Open Questions
- Sample TripSpark Streets export from the partner agency (format, headers, cadence, companion files).
- Whether MDT manual counts map better to TIDES passenger_events or sampling measurements — decide from sample granularity.
- Adapter distribution model (in-repo vs community repo) — Community Maintainer question once a second external adapter appears.

## Addendum — vendor architecture verified (2026-07-14) + handling rules (BINDING)

Vendor documentation reviewed locally (docs/reference/vendor/ — gitignored). Findings at the architectural level:

- The partner agency's report store is the fixed-route product's **SQL Server data warehouse** (the product line runs on SQL Server; its reporting layer is a BI tool reading that warehouse). Integration surface: DBA-curated **read-only views → scheduled CSV export → Headway file-drop** (the docs/sizing.md pattern). This is the FIRST mapping target: MDT manual passenger counts → TIDES passenger_events (or sampling measurements — decide from sample granularity).
- The paratransit product **exports booking records to CSV natively** — SECOND mapping target: bookings → `demand_response_trip` (handoff 0013 contract).
- The vendor's workforce-product REST API (OpenAPI, API-key auth, read-only base tier) is NOT the counts path; noted for a future increment (vehicle-block assignments could enrich block-aware VRH/VOMS). A fixed-route WebServices API also exists; reference docs not on file.

**Trade-secret handling (BINDING for every adapter, this one and all future):** vendor documents marked Trade Secret/Proprietary stay in docs/reference/vendor/ (gitignored) and are ORIENTATION ONLY. No quote, excerpt, page citation, or paraphrase of vendor documentation may appear in any committed artifact. Public mapping specs are derived EXCLUSIVELY from the agency's own data exports (sample fixtures the agency provides from its own systems, anonymized) — an agency describing the shape of its own data is clean; republishing vendor IP is not. The mapping-spec provenance block must therefore reference the SAMPLE (date, provider-agency, anonymization note), never a vendor manual. adapters/README.md must state this rule for community contributors.

Both TripSpark mappings remain BLOCKED on the partner agency's anonymized sample exports (headers + a few rows each). The framework build proceeds now.

## Outputs — framework evidence (ingestion + transform, 2026-07-13)

Framework v0 is built and live-verified. The TripSpark mapping specs themselves remain BLOCKED on samples, per design.

### What shipped

1. **Mapping-spec format** — `contracts/adapter-mapping.v0.schema.json` (machine validation) + `contracts/adapter-mapping.v0.md` (prose). Feature list:
   - source format declaration: `kind: csv` discriminator (encoding incl. BOM/cp1252, delimiter, quotechar, banner-line skip); `fixed_width`/`xml` reserved as future enum members with sibling config blocks, so v0 CSV specs cannot break;
   - field → contract-field mappings with explicit coercions: `string`, `integer`, `decimal` (exact, Decimal end-to-end), `number`, `boolean` (explicit true/false value lists), `date`, `datetime` (strptime format; `%z` kept, naive localized), `enum_map` (explicit vendor-vocabulary table; unmapped values quarantine — never guessed);
   - constants (`const`) and derived fields (`concat`, `local_date_of`);
   - unit conversions (kilometers/meters → statute miles, exact Decimal factor 1 mi = 1609.344 m per NIST SP 811 App. B, fixed 28-digit context for determinism);
   - REQUIRED `timezone` (IANA) — DST-ambiguous and nonexistent wall times QUARANTINE their rows (a timezone transition is never resolved silently);
   - row-filter predicates (`equals`/`not_equals`/`in`/`not_in`/`not_empty`) each with a REQUIRED plain-language `reason`; filtered rows are counted and surfaced as info DQ findings;
   - REQUIRED provenance block per the Addendum: either `sample:` (date, providing_agency, anonymization note — the agency's OWN export) or `synthetic: true` (reference adapters only, forces a `_simulated` source label). A vendor-manual reference is unrepresentable in the schema; per-contract required-field completeness is schema-enforced (`if target_contract == … then fields requires …`).
2. **Adapter runtime** — transform-side Python, `services/transform/headway_transform/adapters/` (`spec.py`, `registry.py`, `engine.py`, `harness.py`). Placement decision (design point 2 allowed Go or Python): Python, because both v0 target contracts land in the transform normalizers — the engine REUSES `tides_passenger_events`/`dr_trips` per-row for contract validation and canonical row construction (contract semantics live in exactly one place), plus literal JSON-Schema validation against `demand-response-trip.v0.schema.json` for DR records. Per-row quarantine via `row_guard`; content addressing on the ORIGINAL vendor bytes; every canonical row carries TWO lineage edges — the normalizer edge and an adapter edge (`transform_name = adapter:<source_label>`, `transform_version` = the mapping spec's content hash) — so "explain this number" names the exact spec version. Envelope source labels are `<vendor>_<product>` (or `…_simulated` for synthetic provenance) and FAIL CLOSED: `raw.vendor.files` messages with an unregistered label are refused (blocking `unregistered_adapter_source` dq.issues row, raw record retained, zero canonical writes); a consumer with no registry refuses everything (`adapter_registry_unavailable`). Registration requires committed sample fixtures; duplicate labels or a broken spec refuse the whole registry at startup. Intake wiring: new generic Go connector `services/ingestion/connectors/vendorfile/` (all 2026-07-13 hardening guards: stability guard, size caps, `rejected/`, fail-closed `VENDOR_SOURCE`, sim-marker structural defense across `, ; | \t` dialects; deliberately NO content check — `parse_status` always `ok`, interpretation belongs to the registered spec) → topic `raw.vendor.files` (added to `contracts/topics.v0.md` + compose `bootstrap-kafka`) → consumer route with the same idempotency guarantees (content-addressed record_id, natural keys + `ON CONFLICT DO NOTHING`, migration-0023 lineage/DQ dedupe).
3. **Validation harness** — `adapters/validate` (CLI, repo root; core in `headway_transform.adapters.harness`): spec machine-valid; every mapped record passes the target contract's validation; every fixture row mapped / filtered (with declared reason) / explicitly quarantined (with reason), counts pinned by committed `<fixture>.expected.json`; deterministic round-trip (double run compared by fingerprint); exit nonzero on any failure. CI: new `adapter-harness` job in `.github/workflows/ci.yml` (style-matched; runs the harness over all registered adapters); mapping specs added to the `yaml-validate` glob.
4. **Reference adapter** — `adapters/_reference/acme/{ridelog,paravan}/`: the invented "Acme Transit Suite" vendor. RideLog (semicolon + single-quote + BOM + 2 banner lines, America/Chicago device clocks) → TIDES `passenger_events`; ParaVan (pipe + cp1252 + km + Y/N flags + day-first datetimes, America/Denver) → `demand_response_trip`. Fixtures exercise EVERY spec feature and every quarantine path (feature matrix: `adapters/_reference/README.md`); the one feature not in fixtures (`datetime` with `%z`) is pinned in unit tests.
5. **Registry docs** — `adapters/README.md`: community how-to (sample → spec → fixtures + expected counts → harness green → provenance) with the Addendum's trade-secret rule stated plainly ("You map YOUR OWN data exports; never republish vendor documentation"; no quote/excerpt/citation/paraphrase of vendor docs in any committed artifact; no reverse-engineering).

### Test counts (before → after)

| Suite | Before | After |
| --- | --- | --- |
| transform (`pytest -q`) | 102 | **131** (+29, `tests/test_adapters.py`) |
| ingestion Go (`go test ./... -count=1 -v`, PASS count) | 37 | **47** (+10, `connectors/vendorfile`) |
| calc / api / ai / db / web (untouched) | 496 / 202 / 109 (+6/6 grounding gate) / 24 / 128 | identical, re-run green 2026-07-13 |

License gate re-run after adding the `pyyaml` dependency (MIT): `python3 scripts/license_gate.py --ecosystem python` → 46/46 PASS. `ci.yml`, `compose.yaml` and both mapping specs validate under `yaml.safe_load`.

### Harness output (real, 2026-07-13)

```
$ python3 adapters/validate
registry: 2 adapter(s) registered (acme_paravan_simulated, acme_ridelog_simulated)
spec acme/paravan -> demand_response_trip (source_label acme_paravan_simulated, spec 12dee2040892): schema + semantic checks OK
  fixture paravan_bookings.csv: rows 11 = mapped 3 + filtered 1 + quarantined 7; canonical 3, edges 6, deterministic OK
spec acme/ridelog -> tides_passenger_events (source_label acme_ridelog_simulated, spec 4a95002c7639): schema + semantic checks OK
  fixture ridelog_empty_day.csv: rows 0 = mapped 0 + filtered 0 + quarantined 0; canonical 0, edges 0, deterministic OK
  fixture ridelog_mixed_day.csv: rows 11 = mapped 2 + filtered 2 + quarantined 7; canonical 2, edges 4, deterministic OK
  fixture ridelog_wrong_export.csv: rows 0 = mapped 0 + filtered 0 + quarantined 0 [file refused]; canonical 0, edges 0, deterministic OK
adapters/validate: ALL CHECKS PASSED   (exit 0)
```

### Live end-to-end run (running compose stack, 2026-07-13/14 UTC)

Path exercised: fixture file dropped → `headway-vendor-file` connector (local binary, `POLL_INTERVAL=2s`, stability guard observed) → MinIO (`raw/vendor/<record_id>.csv`) + `raw.vendor.files` (created idempotently on the live broker; added to `bootstrap-kafka`) → local `python -m headway_transform` with the new `KAFKA_TOPICS=raw.vendor.files` knob and side consumer group `headway-adapters-0015-live` (the live transform container was untouched) → TimescaleDB. psql verification from a SEPARATE connection (container `psql`):

```
        what        | count
--------------------+-------
 raw_vendor_records |     2      -- both fixture files, content-addressed
 passenger_events   |     2      -- source='acme_ridelog_simulated'
 dr_trips           |     3      -- source='acme_paravan_simulated'
 normalizer_edges   |     5      -- normalize_tides_passenger_events / normalize_dr_trips
 adapter_edges      |     5      -- transform_name LIKE 'adapter:acme%'
 dq_quarantined     |    14      -- adapter_row_quarantined (7 ridelog + 7 paravan, all reasoned)
 dq_filtered        |     2      -- adapter_rows_filtered (1 per file, with the spec's reason)
```

Row-level spot checks: `1207:00001 | 2026-03-07 14:15:00+00 | Passenger boarded | 2` (Chicago 08:15 CST correctly rendered UTC; NULL `event_count` preserved on the second row); `AC-1001 | DO | onboard_miles 3.2311301996…` (5.2 km exact-converted), `AC-1002 | PT | no_show=t | riders 0`, `AC-1009 | sponsored=t | MEDICAID`. Lineage walk for one row shows BOTH edges: `normalize_tides_passenger_events@0.1.1` and `adapter:acme_ridelog_simulated@4a95002c7639` (the spec file's content hash), both anchored to the vendor file's record_id.

**Redelivery idempotence:** both fixture files re-dropped byte-identical → connector re-produced (topic end offset 2 → 4) → consumer group re-consumed to offset 4 → every count above UNCHANGED (raw, canonical, lineage, dq) — zero new rows, including findings (migration-0023 `dedupe_key`).

**Fail-closed live:** a file produced under unregistered label `tripspark_streets` → blocking `unregistered_adapter_source` dq.issues row naming the registered labels, raw record retained (`raw.records` count 1 for that source), canonical rows from it: 0.

### Deviations and notes

1. **Topic `raw.vendor.files`** added to `contracts/topics.v0.md` and `deploy/compose/compose.yaml` `bootstrap-kafka` under this handoff's authority (design point 2 requires the intake wiring). Following the handoff-0013 precedent for `raw.dr.trips`: flagged here for explicit Platform Architect ratification.
2. **Machine-push intake for vendor files** (an API-side `POST /ingest/vendor/files` analog of the DR push path) was NOT built — the file-drop path is the design's named intake and the API service belongs to Backend. Open question for a follow-up handoff if agencies want HTTPS push for vendor exports.
3. **Source-label rule extension:** the handoff specifies `<vendor>_<product>`; the framework additionally REQUIRES `<vendor>_<product>_simulated` when a spec's provenance is `synthetic: true` (and forbids the suffix otherwise) — a direct application of the handoff-0005 binding rule so the reference adapter's synthetic rows can never masquerade as real vendor data. Schema- and registry-enforced.
4. **`datetime` with explicit `%z`** is exercised by unit test rather than a reference fixture (both invented formats use naive local clocks, which is also the TripSpark-realistic case).
5. Live-run operational notes: sourcing the whole compose `.env` into the connector's environment accidentally re-triggered the one-shot GTFS-static fetch (harmless — idempotent upserts of the current MBTA feed, but it held a minutes-long live-transform transaction that serialized my first consumer attempt); and a SIGKILLed consumer left an orphaned idle-in-transaction backend holding the content-addressed `raw.records` insert, blocking replays until terminated — recorded in `services/transform/README.md` (stop the consumer with SIGTERM/SIGINT; it shuts down cleanly).
6. `services/transform` gained a runtime dependency on `pyyaml` (MIT; license gate re-run green) and `__main__` gained two operational knobs: `KAFKA_TOPICS` (subset subscription, typo-refusing) and `HEADWAY_ADAPTERS_DIR` (registry location; missing-and-unconfigured degrades LOUDLY to refusing vendor files; present-but-broken refuses startup).
7. `services/transform/Dockerfile` now ships the adapter-mapping and demand_response_trip contract schemas (the adapter runtime loads them at import — without this the new image would crash at startup) plus `adapters/` with `HEADWAY_ADAPTERS_DIR=/app/adapters`. Verified by building the image and loading the registry inside it: `labels in image: ['acme_paravan_simulated', 'acme_ridelog_simulated']` (test image removed afterwards).

Framework green end to end; first real vendor spec drops in the day an agency sample exists.

## Platform Architect ratification — `raw.vendor.files` topic (2026-07-14)

Reviewed per contracts/topics.v0.md governance (0013 precedent): naming follows the registry convention; object_ref encoding matches the file-payload precedent; envelope unchanged; the fail-closed label rules extend correctly (unregistered adapter source → blocking finding, raw retained, zero canonical writes — stricter than prior topics, appropriately, since this topic carries arbitrary vendor formats); the synthetic-provenance ⇔ `_simulated`-label equivalence is a sound extension of the handoff-0005 binding rule. **RATIFIED.** One note for the next increment: the machine-push (HTTPS) vendor intake stays a Backend open question — the file-drop connector is the only intake for this topic today, and the registry entry says so.
