# Vendor Adapter Mapping Spec v0 — field semantics

Companion prose for `adapter-mapping.v0.schema.json` (handoff 0015; ADR-0006). A
mapping spec is a **declarative** description of how one vendor export format maps
onto ONE open Headway contract. Adapters are mappings, never pipeline forks: the
transform runtime (`services/transform/headway_transform/adapters/`) executes the
spec, runs the **target contract's own validation** on every mapped record, and
quarantines per-row through the same hardening machinery every first-party
normalizer uses (`row_guard`, DQ findings, lineage edges).

A worked, fully-featured example lives at `adapters/_reference/` (the synthetic
"Acme Transit Suite" vendor) — it is the template to copy. Contributor rules,
including the binding trade-secret handling rules, are in `adapters/README.md`.

## The one-sentence contract

> Given a file of vendor bytes and a registered mapping spec, the runtime emits
> contract-conformant records, one lineage edge chain per record back to the
> content-addressed raw vendor file, and an explicit reasoned quarantine for every
> row that could not be mapped — deterministically, so redelivery writes nothing new.

## Identity and registration

- `vendor` / `product` — lowercase snake-case identifiers; the spec lives at
  `adapters/<vendor>/<product>/mapping.v0.yaml` (the reference template sits under
  `adapters/_reference/` by sanctioned exception).
- `source_label` — the raw-record envelope `source` this adapter serves:
  `<vendor>_<product>`, or `<vendor>_<product>_simulated` when the provenance block
  declares synthetic fixtures (handoff-0005 binding rule: simulated data is
  permanently distinguishable in provenance). **Fail closed:** the transform runtime
  refuses (blocking DQ issue, raw record retained, zero canonical writes) any file
  on `raw.vendor.files` whose envelope source matches no registered spec.
- `target_contract` — exactly one of:
  - `tides_passenger_events` — the TIDES `passenger_events` table. Field semantics
    are defined by the TIDES specification (pointer in `topics.v0.md`); the runtime
    validates through the transform normalizer whose constraints were verified
    against the published spec — verify against the current spec before extending,
    never from memory.
  - `demand_response_trip` — `demand-response-trip.v0.schema.json` in this
    directory. Mapped records are validated against that JSON Schema *and* the
    transform normalizer's cross-field rules (dropoff ≥ pickup, sponsor iff
    sponsored, a no-show never carries boardings, …).

Registration additionally requires at least one committed fixture under
`adapters/<vendor>/<product>/fixtures/` with expected-count files, green under
`adapters/validate` — a spec without a verified sample fixture cannot be
registered (harness + CI enforce this).

## Source format

`source_format.kind` is a discriminator. v0 implements `csv` only; `fixed_width`
and `xml` are reserved as future enum members that will carry their own sibling
config blocks — adding them cannot break a v0 CSV spec.

For `csv`: `encoding` (Python codec, default `utf-8-sig`), `csv.delimiter`,
`csv.quotechar` (one character each), `csv.skip_leading_rows` (vendor banner lines
before the header). The line after the skip is always the column-name header.
Bytes that do not decode as declared quarantine the **whole file** as a blocking
DQ issue. Structurally hostile rows (oversized fields, NUL bytes, unterminated
quotes absorbing following lines) are quarantined per-row by `row_guard` exactly
as in the first-party normalizers.

## Timezone — declared, never guessed

`timezone` (IANA name) is REQUIRED even when the export carries UTC offsets. Naive
timestamps are localized to exactly this zone. A wall time that is **ambiguous**
(DST fall-back) or **nonexistent** (DST spring-forward) in the declared zone
quarantines the row with a plain-language reason — the runtime never picks a side
of a DST transition silently.

## Filters

`filters` are ordered predicates on raw vendor rows (`equals`, `not_equals`, `in`,
`not_in`, `not_empty`), each with a REQUIRED `reason`. Rows failing a filter are
*excluded by declaration*, counted, and surfaced as one aggregated info-severity
DQ finding per (file, filter) — visible, never silent (Shared Constraint 7).

## Field mappings

`fields` maps **target contract field names** to definitions. Every required field
of the target contract must be present (machine-enforced per contract by the
schema); optional contract fields may be omitted. Each definition is exactly one of:

1. **`from`** — a source column, with optional `coerce`:
   - `string` (default) — stripped; an empty cell means ABSENT (the field is
     omitted; a missing required value is the contract validation's finding, never
     coalesced to a default).
   - `integer`, `decimal` (exact decimal string; Decimal end-to-end, never binary
     float), `number` (for the contracts' float fields, e.g. WGS84 coordinates),
   - `boolean` — via explicit `true_values` / `false_values` lists,
   - `date` / `datetime` — strptime `format`; a datetime without `%z` is localized
     to the spec timezone (with the DST quarantine rules above); with `%z` it keeps
     its own offset. Datetimes are emitted RFC 3339 in UTC (`Z`).
   - `enum_map` — explicit `values` table from vendor vocabulary to contract
     vocabulary; an unmapped source value quarantines the row. Vendor vocabulary is
     mapped explicitly, **never guessed** — and the mapping is derived from the
     agency's own sample, never from vendor documentation.
   - `unit` — optional conversion after `decimal`/`number`, v0: `kilometers`/
     `meters`/`miles` → `miles`, exact Decimal factors (1 international mile =
     1609.344 m exactly — NIST SP 811 Appendix B; verify against the published
     handbook).
   Any coercion failure quarantines the row with the offending value and reason.
2. **`const`** — a constant for every row (e.g. `mode: DR`).
3. **`derived`** — deterministic derivations evaluated after all `from`/`const`
   fields: `local_date_of` (the local wall date, in the spec timezone, of an
   already-mapped datetime target field — e.g. `service_date` from
   `pickup_timestamp`) and `concat` (join source columns with a separator — e.g. a
   stable record id from unit + sequence).

## Provenance (BINDING — handoff 0015 Addendum)

`provenance.verified_against` is either:

- `sample:` — `date`, `providing_agency`, `anonymization`: the agency-provided
  sample export, from the agency's own systems, that the spec was verified
  against. This is the ONLY permitted basis for a real vendor spec. It is never a
  vendor manual reference: no committed adapter artifact may quote, excerpt, cite,
  or paraphrase vendor documentation.
- `synthetic: true` — fixtures are invented; permitted only for reference/template
  adapters (`adapters/_reference/`), and forces a `_simulated` source label.

`verification_date` records when the harness last verified the spec against its
fixtures.

## Runtime guarantees (what a conforming implementation must do)

- **Content addressing on the ORIGINAL vendor bytes**: the raw record is the file
  the vendor pushed; `record_id` = SHA-256 of those exact bytes.
- **Lineage**: every canonical row carries `source_record_id` = the vendor file's
  record id, one normalizer lineage edge, and one adapter lineage edge whose
  `transform_name` is `adapter:<source_label>` and whose `transform_version` is
  the SHA-256 (12 hex) of the mapping spec bytes — "explain this number" can name
  the exact spec version that mapped the row.
- **Accounting**: every vendor data row is exactly one of mapped / filtered (with
  the filter's reason) / quarantined (with a reason). Nothing is dropped silently.
- **Determinism / idempotency**: the same file bytes + the same spec bytes produce
  byte-identical output; redelivery writes zero new rows (unique natural keys +
  `ON CONFLICT DO NOTHING`, migration 0023 patterns).
- **Validation**: `adapters/validate` proves all of the above over the committed
  fixtures; CI runs it for every registered adapter.
