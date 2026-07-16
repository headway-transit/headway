# Vendor Adapters

Headway core speaks **only open contracts** (ADR-0006): TIDES `passenger_events`,
`demand_response_trip` v0, GTFS/GTFS-RT. Vendors get **adapters** — declarative
mapping specs from *your agency's own export files* onto those contracts — never
bespoke pipeline forks. This directory is the adapter registry (handoff 0015).

```
adapters/
  <vendor>/<product>/
    mapping.v0.yaml        # the declarative mapping spec (the contract is
                           # contracts/adapter-mapping.v0.schema.json)
    README.md              # prose: what the export is, how fields map, caveats
    fixtures/
      <name>.csv                  # anonymized sample export rows (agency-provided)
      <name>.csv.expected.json    # pinned row accounting for the harness
  _reference/              # the synthetic "Acme Transit Suite" template (see below)
  validate                 # the validation harness CLI (CI runs it)
```

## The rule that governs everything here (BINDING)

**You map YOUR OWN data exports; never republish vendor documentation.**

- A mapping spec is derived **exclusively** from sample exports your agency
  produced from its own systems and anonymized. An agency describing the shape
  of its own data is clean; republishing vendor IP is not.
- No adapter artifact committed to this repository may **quote, excerpt, cite,
  or paraphrase vendor documentation** (manuals, admin guides, API references,
  schemas). If you used vendor docs to orient yourself, they stay private
  (gitignored, e.g. `docs/reference/vendor/`) — what you publish is only what
  your own export files demonstrate.
- No reverse-engineering of licensed software. Adapters read files a vendor
  system *already exports to you*; agencies own their data.
- The spec's REQUIRED `provenance` block records the **sample** (date,
  providing agency, anonymization note) — the schema makes a vendor-manual
  reference unrepresentable, and CI rejects a spec without it.

## How to add a vendor adapter

1. **Get a real sample.** Export a small file from your own system (headers +
   a few rows). Anonymize it: replace identifiers, drop or jitter locations,
   shift dates if needed — and describe what you did in
   `provenance.verified_against.sample.anonymization`.
2. **Copy the template.** Start from `_reference/acme/ridelog/` (fixed-route
   counts → TIDES `passenger_events`), `_reference/acme/stopcount/`
   (headerless APC stop visits with `emit` fan-out → TIDES
   `passenger_events`), or `_reference/acme/paravan/` (paratransit bookings →
   `demand_response_trip`) — or from the first REAL adapter,
   `tripspark/streets/`. Every mapping-spec feature is demonstrated in
   `_reference/`; format semantics: `contracts/adapter-mapping.v0.md`.
3. **Write `mapping.v0.yaml`** at `adapters/<vendor>/<product>/`:
   - `source_format`: CSV dialect (encoding, delimiter, quote char, banner
     lines to skip). Headerless exports declare `header: false` plus the
     positional `columns` your sample demonstrated (a row with a different
     field count quarantines — positions are never guessed).
   - `timezone`: the IANA zone your export's local timestamps are in.
     **Required, never guessed** — DST-ambiguous/nonexistent wall times
     quarantine their rows rather than being resolved silently.
   - `filters`: which rows are out of contract scope, each with a
     plain-language `reason` (they are counted, never silently dropped).
   - `fields`: every required target-contract field, with explicit coercions,
     enum maps for vendor vocabulary, constants, derived fields, and unit
     conversions. Empty cells are *absent* — never coalesced to defaults.
   - `emit` (optional fan-out): when one export row carries several contract
     events (e.g. a stop-visit row with both a boardings and an alightings
     column), declare one emission per event with per-emission field
     overrides and reasoned `when` suppression predicates (zero counts
     suppress the emission, never a fabricated zero-count event). See
     `contracts/adapter-mapping.v0.md` and `_reference/acme/stopcount/`.
   - `provenance`: the sample block, per the rule above.
4. **Commit fixtures** under `fixtures/`: the anonymized sample file(s), each
   with a `<name>.expected.json` pinning `total_rows` / `mapped` /
   `quarantined` / `filtered` (plus `emitted` for specs with `emit`
   fan-out). A spec without a verified sample fixture
   **cannot be registered**. Good fixtures include the ugly rows — bad enums,
   malformed numbers, contradictions — so the quarantine behavior is pinned too.
5. **Run the harness** until green:

   ```sh
   pip install -e services/transform
   python3 adapters/validate                       # all registered adapters
   python3 adapters/validate adapters/<vendor>/<product>/mapping.v0.yaml
   ```

   It proves: spec machine-valid; every mapped record passes the target
   contract's validation; every fixture row is mapped, filtered (with reason),
   or explicitly quarantined (with reason); deterministic round-trip. CI runs
   the same harness — a registered adapter with a red harness fails the build.
6. **Write the prose `README.md`** next to the spec: what the export is, where
   it comes from in your workflow, field-mapping rationale, known caveats.
   Same trade-secret rule applies: your words about your data only.

## Running an adapter in the pipeline

Point the ingestion vendor-file connector at a drop directory and label it
with your registered spec's `source_label`:

```sh
VENDOR_DROP_DIR=/srv/headway/drop/<vendor>_<product> \
VENDOR_SOURCE=<vendor>_<product> \
KAFKA_BROKERS=... S3_ENDPOINT=... ./headway-ingest
```

The connector lands the ORIGINAL bytes content-addressed (SHA-256 record_id),
produces to `raw.vendor.files`, and the transform consumer maps the file with
your registered spec. **Fail closed:** a source label that matches no
registered spec is refused — raw record retained, blocking DQ issue, zero
canonical rows. Redelivery of the same bytes writes zero new rows (idempotent
by content address + natural keys). Every canonical row carries lineage to the
raw vendor file and to the exact mapping-spec version (content hash) that
mapped it.

## The reference adapter (`_reference/`)

"Acme Transit Suite" is an **invented** vendor: RideLog (semicolon-delimited,
single-quote quoting, BOM, banner rows, local device clocks in
America/Chicago) and ParaVan (pipe-delimited, cp1252, km distances, Y/N flags,
day-first dates in America/Denver). It exists so the harness has a test bed
exercising every mapping-spec feature and every quarantine path, and so
contributors have a complete template. Because its fixtures are synthetic, its
provenance declares `synthetic: true` and its source labels end in
`_simulated` — only reference/template adapters may do this; real adapters use
the sample provenance block and a plain `<vendor>_<product>` label.

## Governance

- The mapping-spec format itself is a wire contract
  (`contracts/adapter-mapping.v0.schema.json`) governed by the Platform
  Architect; format changes require an ADR-linked handoff.
- Adapter certification is earned by a green harness against these contracts —
  never by payment (GOVERNANCE.md anti-capture rules).
- First-party TripSpark specs (handoff 0015): **`tripspark/streets/` is live**
  (fixed-route APC stop visits → TIDES `passenger_events`, verified against
  the partner agency's own sample export 2026-07-16 — the first real
  adapter). The paratransit bookings → `demand_response_trip` spec still
  awaits its sample export (BLOCKED by design: field semantics never come
  from memory or vendor docs).
