# Handoff: ntd-compliance-engineer → data-engineer, backend-engineer — Gap policy: calc v0.2 (per-group exclusion + coverage)

## Context
The 2026-07-09 live run proved vrm_v0/vrh_v0 0.1.0's all-or-nothing gap refusal blocks any realistic full-fleet window (122 gapped groups out of a fleet-day → total refusal). The mature policy: exclude gapped vehicle-trip groups from the figure, report coverage explicitly, and refuse only when coverage falls below a certifiability threshold. This handoff specifies calc version 0.2.0 and the one schema extension it needs.

## Inputs (what receiving roles are given)
- Live evidence in handoff 0001 (2026-07-09 sections).
- Existing calc package `services/calc` (0.1.0 stays runnable; goldens pinned to it remain).

### Policy specification — vrm_v0 / vrh_v0, CALC_VERSION 0.2.0
1. **Grouping unchanged:** per `(vehicle_id, trip_id)`, trip-assignment as revenue-service proxy (still an approximation — see Verification status).
2. **Per-group exclusion:** a group containing a gap > `gap_threshold_seconds` (explicit input, default 300) is **excluded** from the summed figure. Each excluded group emits one DQ finding, `issue_type='telemetry_gap_excluded'`, severity **warning** — the figure itself is not wrong; the exclusion is documented and owned.
3. **Coverage:** `coverage = clean_groups / total_groups` (also report clean-position share). Coverage and exclusion counts are part of the result.
4. **Certifiability line:** if `coverage < coverage_threshold` (explicit input, default 0.95 — an agency-policy parameter, not an FTA number; FTA sampling/completeness expectations must be verified against the current NTD Policy Manual before this default is treated as more than an engineering placeholder), the run emits ONE **blocking** issue (`issue_type='coverage_below_threshold'`) and **does not persist** — the guardrail "never emit a certifiable value over an unresolved DQ gap" holds at the threshold line.
5. **Provenance narrows correctly:** `input_record_ids` (→ lineage.edges) include **only records from included groups**. Excluded groups' records are cited by their DQ findings instead.
6. **Persisted detail:** value rows carry `{coverage, total_groups, excluded_groups, clean_position_share, gap_threshold_seconds, coverage_threshold}` in a new `detail JSONB` column.
7. **Versioning discipline:** CALC_NAME unchanged (`vrm_v0`/`vrh_v0`), CALC_VERSION → `0.2.0`; 0.1.0 remains runnable; REGULATORY_TRACKER gains a 0.2.0 row (status PRE-VERIFICATION; FTA manual access pending — verification attempted 2026-07-10, transit.dot.gov bot-blocked; the 2025 NTD Full Reporting Policy Manual must be obtained and the VRM/VRH/deadhead/layover definitions quoted in the tracker before any figure is treated as reportable).

## Outputs (what each receiving role must produce)
- **Data Engineer:** migration `0010_metric_values_detail.sql` adding `detail JSONB NOT NULL DEFAULT '{}'` to `computed.metric_values` (append-only extension; no existing column changes).
- **NTD/Compliance (self):** calc 0.2.0 per the spec; golden dataset extended with an exclusion case (gapped group excluded, value persisted, coverage exact); all 0.1.0 goldens untouched and green; runner passes thresholds through and persists per rule 4.
- **Backend Engineer (no code change expected):** confirm the existing certify rule (refuse on any open blocking issue) composes with rule 4 — sub-threshold runs never persist, passing runs carry only warnings, so certification is reachable exactly when coverage passes. Respond in this handoff.

## Open Questions
- The 0.95 default coverage threshold is an engineering placeholder pending FTA guidance verification and, ultimately, per-agency configuration (owner: NTD role, then Backend for config surface).
- Whether excluded-group warnings should auto-resolve when a later replay fills the gap (owner: Data Engineer, slice 2).

## Verification Evidence
- Live-run evidence motivating the policy: handoff 0001, 2026-07-09 sections.
- FTA definition verification ATTEMPTED and blocked (transit.dot.gov 403 for HTML and PDF from this environment, 2026-07-10); manual to be supplied by repo owner; tracker rows stay PRE-VERIFICATION until quoted.
- **2026-07-10 — implemented and live-verified end to end:**
  - Calc 0.2.0: 68 tests green (23 new; all 0.1.0 goldens byte-identical and green). Migration 0010 applied live via the new PG* path.
  - Live run 1 (defaults, 0.95): coverage 0.9263 over 2,742 groups (202 excluded) → **refused as designed**, one blocking `coverage_below_threshold` per metric, 404 warnings routed.
  - Live run 2 (agency threshold 0.90): **first persisted figures — VRM 12,794.92 mi / VRH 1,260.85 h**, detail JSONB carrying coverage/thresholds/exclusions; lineage traversal live via API: metric → 326 content-addressed raw records through vrm_v0 0.2.0.
  - Full workflow: certify refused (409, 246 open blocking) → steward resolved 246 with documented resolutions → certification 201 → **verified in psql**: both metrics `certified`, 1 certification row, audit trail dq_resolve ×246 + certify ×1.
  - **Critical bug found by live verification and fixed:** the API's psycopg3 connection defaulted to `autocommit=False`; the first read opened an implicit transaction nothing committed, so every router `transaction()` block nested as a savepoint — the API returned 201 while zero rows reached disk (a certification that would have evaporated on restart). Fix: `autocommit=True` in the lifespan (db.py) + regression tests (`test_transaction_discipline.py`, 39 API tests green) including a fake that honestly models psycopg3 nesting semantics. The unit-test fake had masked this — a CI integration job against a real PostgreSQL (Actions service container) is the standing follow-up.
- Backend response to rule 4 (compose-with-certify check): confirmed live — sub-threshold runs persist nothing; the passing run carried only warnings; certification became reachable exactly when blocking issues were resolved.

## Response — backend-engineer (per-agency config surface, 2026-07-10)

The first Open Question's config half is now built: migration
`db/migrations/0014_app_settings.sql` creates `app.settings` and SEEDS the
four calc policy knobs with plain-language descriptions citing each default's
basis — `coverage_threshold` `0.95` (ENGINEERING PLACEHOLDER, not an FTA
number, per REGULATORY_TRACKER.md; the measured MBTA trip-level structural
coverage ~0.914 is why this must be per-agency policy), `gap_threshold_seconds`
`300` (engineering default, this handoff's rule 2), `layover_max_seconds`
`1800` (data-informed + Exhibit 35-aligned, per-agency configurable per the
tracker), and `missing_trip_threshold` `0.02` (the REAL FTA threshold, 2026
NTD Policy Manual p. 146). API surface: `GET /settings` (any signed-in role —
policy visible to the people it governs) and `PUT /settings/{key}`
(certifying_official only; value validated against the row's `value_type`,
decimal via `Decimal` — floating point never touches a policy number; plain-
language 422 on a bad value; old→new in the audit detail; unknown key 404 —
settings are seeded, never client-creatable).

**EXPLICIT LIMITATION — the calc runner does NOT yet read `app.settings`.**
Every run is still governed by the runner's explicit CLI flags
(`--coverage-threshold`, `--gap-threshold-seconds`, `--layover-max-seconds`,
`--missing-trip-threshold`); a value set through the API changes no
calculation until the runner-reads-settings increment wires the two together
(owner: Backend, next increment; the NTD role's placeholder-verification
question above stays open regardless). This surface ships first so agencies
have ONE audited place to set policy and the web team a stable contract.

Verification (2026-07-10, Python 3.12, fakes only — live DB/stack untouched;
migration 0014 NOT applied live by this work): `services/api` suite 90
passed (76 pre-existing + 14 new); `db` static migration suite 13 passed
(new `test_app_settings_seeded_with_calc_policy_knobs`); `openapi.json`
regenerated — 15 paths, now including `/settings`, `/settings/{setting_key}`,
and `/machine/metrics` (the `read:metrics` consumer from handoff 0006).

### Note — backend-engineer (runner-reads-settings shipped, 2026-07-11)

The **EXPLICIT LIMITATION** paragraph above is now REMOVED — the paragraph
itself stands unedited as history; this dated note supersedes it. The
runner-reads-settings increment shipped: `run_period` reads the four seeded
knobs from `app.settings` via the new `headway_calc/settings.py`
(`load_policy_settings` → frozen `PolicySettings`; decimal values parsed with
`Decimal`, never float; integers for the seconds knobs), so a threshold set
through the audited `PUT /settings/{key}` API governs the next run with no
flag needed.

**Precedence (per threshold, highest wins): explicit CLI flag/argument >
app.settings row > code default** — and every RunReport now records each
threshold's provenance (`threshold_sources`:
`"explicit" | "settings" | "default"`), so the persisted detail JSONB's
threshold values have their origin story in the report.
(`imbalance_threshold` is not a settings knob: only explicit/default.)

Failure is loud and typed: a table that exists but is missing a knob row or
holds an unparseable/wrong-typed value raises
`headway_calc.settings.SettingsError` and the run REFUSES before reading any
canonical row — no silent code-default fallback once the table exists, never
a guessed threshold. The ONE tolerated absence is the table itself
(relation-does-not-exist, SQLSTATE 42P01 — a pre-0014 database): the runner
proceeds on code defaults with an explicit WARNING log.

New CLI flag `--ignore-settings` skips the `app.settings` read entirely, for
reproducing historical runs: per REGULATORY_TRACKER.md's rule ("shipped
versions are never deleted or rewritten"), a historical reproduction uses the
PINNED calc versions plus the EXPLICIT thresholds recorded in the original
RunReport — never whatever `app.settings` holds today.

Verification (2026-07-11, Python 3.12, fakes only — live DB untouched):
`services/calc` suite 185 passed (157 pre-existing + 28 new:
`tests/test_settings.py` and the settings-precedence/provenance runner tests
in `tests/test_runner.py`, including the full explicit>settings>default
matrix over all four knobs, corrupt-value refusal, missing-table fallback
with warning, and determinism across the settings path).
