# Handoff: ntd-compliance → calc, backend — Day-type service calendar + monthly agency workbook export

## Context
Agencies hand-assemble a monthly metrics workbook (per-mode UPT, average weekday/Saturday/Sunday ridership, typical/atypical service splits, VOMS/VAMS, days operated, missed-trip accounting, year-over-year). Analysis of a partner agency's real workbook (local reference only, docs/reference/vendor/ — its LAYOUT/branding is never copied; the METRICS are NTD-universal concepts) confirms the shape maps ~1:1 onto figures Headway computes or can compute. The killer feature: Headway emits the familiar monthly workbook automatically, a receipt behind every cell. Missing prerequisite: day-type classification (weekday/saturday/sunday service days + atypical-day flags) — also the standing blocker for VOMS atypical-day exclusion (handoff 0009 open question) and the Exhibit 44 day-type schedules.

## Design (binding)
1. **Day-type service calendar (calc + settings):** classify each service_date in a period as weekday/saturday/sunday SCHEDULE day (v0: day-of-week from the canonical data's service dates; if GTFS calendar/calendar_dates are available in canonical use them — inspect; if not, day-of-week + documented divergence) with an agency-configurable overrides surface in app.settings (holiday reassignments e.g. "2026-07-04 runs sunday schedule"; atypical-day flags with reasons) following the audited settings + provenance pattern (migration if a table beats settings rows — smallest honest design, document). `daytype_v0` 0.1.0 with tracker/OPS-DEFINITIONS placement decided by what it feeds: it feeds NTD figures (day-type averages appear in NTD reporting), so REGULATORY_TRACKER row citing what the Full Reporting manual says about average weekday/sat/sun schedules and Days Operated (find + quote the exact pp. — the Days Operated requirement is around printed p. 155, quoted partially in the PMT verification pass; NEVER from memory).
2. **Day-type figures:** average weekday/saturday/sunday UPT per mode for a month (sum UPT on days of that type ÷ days of that type operated), days-operated counts per day type; typical/atypical splits WHERE the atypical flags exist (unflagged months = all typical, stated). Persisted via the standard calc pathway (versioned, receipts, per-mode scoping); refusal discipline inherits UPT's (a day-type average over refused UPT days refuses with the same receipts).
3. **Monthly agency workbook export (api):** GET /reports/agency-workbook?month= producing XLSX via the exports.py machinery — OUR OWN generic layout (never the partner file's): "Read first" banner sheet (NOT-REPORTABLE/simulated/certification block per existing pattern), a Ridership-by-mode sheet (UPT totals, day-type averages, days operated, YoY columns computed from persisted history where it exists — absent cells STATED ("not yet computed by Headway" / "no figure for this period"), never invented, never zero-filled), an Operations sheet (VOMS + ops-category OTP/cvh clearly badged as operations metrics per the 0024 wall). Every data cell's provenance available: a per-sheet hidden-or-visible provenance column with metric_value_ids (visible — we're proud of it). CSV variant via the same grid.
4. **Honest scope:** missed-trip accounting (their "Ranger down" rows) NOT in v0 — it needs schedule-vs-operated reconciliation semantics we haven't verified; state the row's absence in the workbook README sheet as a known future increment. VAMS = not computed (needs fleet inventory data we don't ingest); stated absent.

## Outputs
daytype calc + settings surface, day-type figures persisted, workbook XLSX/CSV endpoint, tests + goldens (hand-worked day-type month), live workbook generated for a real month against MBTA data, suites green, evidence here.

## Open Questions
- Atypical-day auto-detection (service-level anomalies) — future; v0 is agency-declared only.
- Missed-trip reconciliation calc — needs verification work; natural next wave with the TripSpark data.
- Per-agency workbook layout theming — after the generic one proves itself.

## Response (calc + backend, 2026-07-15)

Contract accepted and delivered. Deviations from the letter, reported here rather than silently absorbed:

1. **Year-over-year columns show NO derived delta.** The workbook's YoY columns are the prior-year month's persisted figure VERBATIM plus its own provenance id (`prior_year_value`, `prior_year_provenance`). `exports.py`'s standing invariant is "formatting, NEVER arithmetic," and the one blessed comparison affordance already exists (`GET /metrics/compare`, exact-Decimal, sign-neutral per the calc registry). The workbook banner states this and points at the compare surface. If the intended reading of "YoY columns computed from persisted history" was a delta column, that is a one-line follow-up in the ROUTER (the compare precedent) — deliberately not done unprompted.
2. **`daytype_v0` 0.1.0 is the CLASSIFICATION identity, never itself a metric row** (the passages-derivation precedent). The persisted figures carry their own calc names — `daytype_days_operated_v0` 0.1.0 → metric `days_operated` (unit `days`) and `daytype_upt_avg_v0` 0.1.0 → metric `upt_avg` (unit `unlinked_passenger_trips_per_day`) — because `headway_calc.persist` maps one calc_name to one metric. The classification's name + version + every governing override row snapshot into each figure's detail JSONB.
3. **Days Operated is agency-level in v0** (scopes `daytype:<type>`); per-mode days-operated is documented as not implemented (tracker row). The averages ARE per-mode (`--per-mode` → `mode:<m>:daytype:<type>[:atypical]`).
4. **voms_v0's atypical-day exclusion (handoff 0009 open question) is now UNBLOCKED but deliberately NOT implemented** — changing VOMS semantics mints voms_v0 0.2.0 with its own tracker row and goldens; natural next increment.
5. **The typical average excludes declared-atypical days** (their own stated split rows). Honesty note recorded in the tracker's citation column: no manual sentence prescribes that exclusion for ridership averages (the quoted atypical language is the monthly manual's VOMS rule); it is a documented Headway convention pending per-form verification.
6. **Overrides table is mutable-with-audit, not append-only** (the app.settings precedent, documented in migration 0031's header): an override is policy configuration, not evidence — every figure computed under one snapshots the full row into its own detail, so history rides the figure; the API audits old→new on every change.
7. **License gate:** green only after two environment fixes on this dev box, both pre-existing and unrelated to this wave's diff (no dependency manifests touched): the gate's own documented GOROOT workaround for the auto-fetched go toolchain, and excluding the gitignored `.ds-sync` self-symlink `web/node_modules/web -> ..` for the run (restored immediately after); `pandas` (a `clients/python` declared dep) was additionally installed into the venv so the python scan could verify it.

Open questions inherited/added: atypical auto-detection (v0 is declared-only, per the handoff); GTFS calendar/calendar_dates ingestion (would make the operated schedule feed-derivable — canonical has none today, inspected); agency-service-day convention (v0 buckets by UTC calendar date, the voms_v0 convention — positions carry no service_date); strikes/emergencies "days not operated" declarations (stated absent in the workbook); per-mode days operated.

## Outputs — backend evidence (2026-07-15)

**Suites (all green, grown):**

```
services/calc  $ python3 -m pytest tests/ -q            567 passed   (was 537; +30: test_daytype 20, test_golden_daytype 4, test_runner_daytype 6)
services/api   $ python3 -m pytest tests/ -q            296 passed   (was 279; +17: test_service_days 11, test_workbook 6)
db             $ python3 -m pytest test_migrations_static.py -q   29 passed  (+1: test_service_day_overrides_validated_and_meaningful)
services/api   $ python3 scripts/export_openapi.py      50 paths — /reports/agency-workbook, /settings/service-days, /settings/service-days/{service_date} present; openapi.json regenerated (drift gate satisfied)
repo           $ python3 scripts/license_gate.py        LICENSE GATE: PASS — 218 dependencies conform (go 27, python 53, node 138; see Response item 7 for the two environment fixes)
```

**Tracker:** new section "Verified — Days Operated and day-type schedules (verified 2026-07-15)" with the pp. 154–156 sentences quoted verbatim from the 2026 Full Reporting PDF (extracted 2026-07-15, printed-page numbers confirmed against page footers: Days Operated bullets + per-schedule breakdown p. 155; holiday/availability/partial-day rules p. 156; average-schedules sentence p. 154) + three new table rows (daytype_v0, daytype_days_operated_v0, daytype_upt_avg_v0, all 0.1.0).

**Goldens:** `tests/golden/daytype_v0/{fixture.json, expected.json, BASIS.md}` — hand-worked February 2026: holiday reassignment (2026-02-16 → sunday, the p. 156 rule), declared atypical Saturday (2026-02-14); days operated 2/2/2 with per-type unobserved warnings; averages weekday 45.00, saturday-typical 25.00 (atypical 14th EXCLUDED), saturday-ATYPICAL 60.00 (own split), sunday 15.00 (the reassigned holiday's 18 boardings land in the SUNDAY average); plus the refused-day case (missing share 1/2 > 0.02 → the weekday average refuses with `daytype_average_over_refused_days` + the day's own p. 146 refusal propagated date-prefixed — the same receipts; days_operated still counts the day: observation-derived, blocking-free).

**Migration 0031 live-applied + psql-verified + proven by attack:**

```
$ python3 db/migrate.py                     applying 0031_service_day_overrides.sql ... ok
schema_migrations tail: 0031, 0030, 0029
app.service_day_overrides columns: service_date DATE PK; assigned_day_type TEXT NULL; atypical BOOL NOT NULL; reason TEXT NOT NULL; updated_by; updated_at
constraints: day_type_vocabulary, meaningful, pkey, reason_not_blank — all three CHECKs proven by live attack (CheckViolation on bad vocabulary / meaningless row / blank reason)
```

**Live settings surface (API restarted on 127.0.0.1:8000 with env preserved from /proc):** logged in as `certifier` (certifying_official); declared via `PUT /settings/service-days/...`:

- `2026-07-03` → `assigned_day_type: sunday` ("Independence Day observed (2026-07-04 falls on a Saturday): agency operates the Sunday schedule …p. 156") — audit event 868;
- `2026-07-09` → `atypical: true` (demo declaration, honestly labeled) — audit event 869.

Both psql-verified in `app.service_day_overrides` and `audit.events` (`service_day_override_set`, actor `certifier`).

**Live day-type run (real MBTA-fed data, month 2026-07):** `python -m headway_calc.runner --period-start 2026-07-01 --period-end 2026-08-01 --daytype --per-mode` — 2,279,421 positions (Jul 9–11) + 204,524 passenger events (Jul 9–13, all `tides_simulated`) + 2 overrides + 0 attestations; missing_trip_threshold 0.02 from `settings`. **9 persisted / 18 honestly refused:**

| figure | scope | value | evidence |
|---|---|---|---|
| days_operated | daytype:weekday | **2** (Jul 9 atypical + Jul 10) | warning `daytype_days_unobserved` (20 weekday dates untelemetered — observed lower bound) |
| days_operated | daytype:saturday | **1** (Jul 11) | same warning (3 dates) |
| days_operated | daytype:sunday | **0** | the reassigned Jul 3 counts as a sunday date but had no telemetry — stated, never invented |
| upt_avg | daytype:weekday:atypical | **238,100.00** | Jul 9: 235,725 counted boardings × factor 1.010075 (missing 91/9,123 = 1.0% ≤ 2%, the p. 146 ≤2% branch); simulated-flagged |
| upt_avg | mode:bus / tram / subway / rail / unknown :daytype:weekday:atypical | **173,887.00 / 17,508.00 / 7,011.00 / 5,489.00 / 34,204.00** | per-mode splits of the same day |
| upt_avg | daytype:weekday (typical) | **REFUSED** | Jul 10: 10,431 of 17,876 operated trips missing (58.3% > 2%) → day refused → average refused with the day's receipt propagated (`daytype_average_over_refused_days` + `apc_missing_trips_above_fta_threshold`) |
| upt_avg | daytype:saturday (typical) | **REFUSED** | Jul 11: 0 events for 2,982 operated trips (100% missing) |
| upt_avg | daytype:sunday | **REFUSED** | `daytype_no_operated_days` — an average over nothing is never invented |

psql-verified: 9 `computed.metric_values` rows (category `ntd`, uncertified), lineage edges present per row (ONE per upt_avg row — correct: all 111,568 Jul-9 events share one raw record, the single simulated CSV push; days_operated rows cite the earliest in-trip position record per counted day), dq.issues carry the run's receipts (12 blocking p. 146 refusals, 12 `daytype_average_over_refused_days`, 6 `daytype_no_operated_days`, 3 `daytype_days_unobserved`, 404 + 222 per-day p. 151 warnings, 12 aggregated `simulated_source_data` infos), and the atypical figure's detail JSONB carries the FULL override row snapshot (reason + updated_by + updated_at) — the declaration rides the figure.

**Live workbook (`GET /reports/agency-workbook?month=2026-07`):** XLSX 11,868 bytes / CSV 17,575 bytes, verified programmatically:

- sheets `['Read first', 'Ridership by mode', 'Operations']`; CSV and XLSX **cell-for-cell byte-equal** (banner lines = "Read first" rows; each CSV `## <title>` marker = the XLSX tab name); every non-empty cell a TEXT cell;
- banner: NOT-REPORTABLE lead, how-to-read (verbatim strings + provenance column + lineage pointer), stated-absence convention, YoY-no-delta statement pointing at `/metrics/compare`, daytype_v0 basis + tracker citation, typical/atypical statement, missed-trips + VAMS honest-scope absences, the migration-0024 ops badge statement, the SIMULATED banner (simulated rows present), and the period's CERTIFICATE BLOCK — three certifications listed (one pre-signature legacy line "recorded before digital signatures existed… honest history, never backfilled" + two Ed25519-signed lines with typed signer and key fingerprint);
- Ridership sheet: the live 238,100.00 atypical average with visible provenance id `4c50f055…` and `SIMULATED DATA - MUST NOT BE SUBMITTED`; per-mode atypical rows each with their own provenance ids; Days operated 2/1/0 with observed-lower-bound notes from the persisted detail; EVERY uncomputed cell reads "no figure for this period — not yet computed by Headway" with empty provenance (UPT month totals, typical averages — refused, receipts in dq.issues; missed trips and days-not-operated stated as not computed); prior-year columns all "no figure for this period" (no 2025-07 rows exist);
- Operations sheet: VOMS 1204 (category `ntd`), OTP 54.10 and headway adherence 0.3010 (category `ops`, each row carrying the never-certifiable badge note verbatim), VAMS stated absent with the fleet-inventory reason.

**Docs:** `services/calc/README.md` (new daytype section + What-ran entry), `services/api/README.md` (four new endpoint rows + verification entry), migration 0031 header (design decision documented), tracker as above. No commits made (per instruction); `web/`, `clients/`, `notebooks/` untouched.
