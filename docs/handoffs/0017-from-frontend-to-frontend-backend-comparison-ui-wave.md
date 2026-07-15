# Handoff: design review → frontend, backend — Comparison surfaces, status cards, themed chrome (UI wave from partner-agency reference)

## Context
A partner agency shared screens from an internal application (reference imagery local-only in docs/reference/ui-inspiration/, NEVER committed or reproduced; this handoff describes patterns, not pixels). Design review verdict (2026-07-14): adopt the comparison/status/progress patterns into the generic shell; adapt the what-if surface behind our honesty walls; extend branding from logo+colors to themed chrome. Out of the box stays neutral Headway — theming is per-agency opt-in through the existing audited branding surface.

## Design (binding)
1. **Comparison cards + matrix (frontend + small backend):** a /compare surface where the user picks a metric and 2–4 comparands (calc versions of the same figure; or adjacent periods) → card row (big value, delta vs baseline comparand and vs previous, per-mode subline) + a detail matrix (rows = modes/scopes, columns = comparands, cells = value + signed delta). RULES: every cell keeps the receipt affordance (click → Receipt); deltas are SIGN-NEUTRAL styling (direction glyph + magnitude; red/green ONLY where the metric defines better/worse, e.g. coverage — encode that in the metric registry, not per-view); simulated/ops badges carry through; comparisons of certified vs uncertified figures label both. Backend: GET /metrics/compare (params: metric, scope set, comparand list) composing existing reader queries — no new computation, composition only.
2. **Severity/status summary cards** above /dq, /safety, and the deadlines panel: count cards with a colored top border + label (severity for DQ, classification for safety, urgency for deadlines), each card acting as a filter toggle. Counts come from existing endpoints (extend with a counts param if needed — no new tables).
3. **Progress bars in table rows:** sampling plans list (measured/required per plan, the estimate-ready state visually distinct); reuse for any future checklist-shaped entity. Accessible: value + label text, never bar-alone.
4. **Toasts + breadcrumbs (shell polish):** action-confirmation toast pattern (aria-live polite) adopted shell-wide for create/supersede/certify actions; breadcrumbs on deep entities (sampling plan → draw → measurements; safety event → supersede chain; receipt → lineage).
5. **XLSX export alongside CSV** where grids/export exist today (MR-20 preview, S&S-50 package, sampling worksheet, /metrics values): openpyxl (MIT — license gate) server-side; identical numbers to the CSV (test: byte-equal values cell-for-cell), NOT-REPORTABLE/simulated banners as a first sheet where the CSV has banner lines.
6. **Settings sandbox (what-if modeling) — the adapted deep idea:** a /sandbox surface: pick a knob set (coverage_threshold, layover_max_seconds, otp windows), propose values, run a PREVIEW recomputation for a chosen period → live impact rail (figure deltas vs current settings). HARD WALLS: previews persist ONLY as category='ops' rows tagged sandbox (or ephemeral — implementer picks the smaller honest design and documents it); never certifiable, never in MR-20/public/certify (the 0024 CHECK already guarantees the category wall); the surface states "modeling preview — changes nothing" and a separate explicit existing settings-change flow (audited) applies anything. Runner gains a bounded preview entry point ONLY if the existing --ignore-settings/explicit-flag path can't serve; prefer composition.
7. **Themed chrome (branding v2):** extend branding settings with nav-chrome theming (header background, active-accent, optionally themed nav) applied to the app shell; server-side WCAG refusal extends to the new chrome pairs (branding.py math reused); default remains neutral Headway; per-mode (light/dark) variants respected per the known limitation (a theme failing dark simply doesn't apply in dark — stated, not silent).
8. **Honest scope:** no in-place editing of canonical data anywhere (append-only stands); the sandbox is the ONLY editable-what-if surface and edits knobs, never data.

## Outputs
Backend: compare endpoint, counts params, XLSX exports, sandbox preview path, branding v2 fields+validation. Frontend: /compare, summary cards, progress bars, toasts/breadcrumbs, /sandbox, themed chrome. All suites green + axe/contrast/build; live click-through evidence; evidence here.

## Open Questions
- Metric-registry "direction" metadata (which metrics define better/worse) — start with coverage only; expand deliberately.
- Sandbox preview persistence vs ephemeral — implementer documents the choice.
- Themed chrome dark-mode brand variants — known standing limitation, unchanged.

## Response — backend (2026-07-15)

Contract accepted for the backend half (design points 1, 2, 5, 6, 7). All
delivered on working tree at commit 1707a8f (uncommitted, per wave rules);
`services/api/openapi.json` regenerated — the frontend codes against it.

**Endpoint contracts (binding for the frontend):**

1. **`GET /metrics/compare`** — params: `metric` (e.g. `vrh`), 2–4 repeated
   `comparand` params of the form `<start>..<end>` (ISO dates, half-open
   period exactly as computed) optionally `@<calc_name>:<calc_version>`
   (version-pinned — "calc versions of the same figure" = same period,
   different pins), optional repeated `scope` (default: every scope with a
   figure in any comparand, `agency` first). First comparand = baseline.
   Response: `{metric, unit, comparands:[{key, period_start, period_end,
   calc_name?, calc_version?, baseline}], scopes, rows:[{scope,
   cells:[{comparand_index, value: <FULL /metrics/values row incl.
   metric_value_id/detail/category/certification_status> | null,
   missing_reason, delta_vs_baseline, delta_vs_previous}]}], directions,
   direction_note, delta_note, mixed_certification,
   mixed_certification_note}`. Composition only: one `query_metric_values`
   call per comparand + the mr20 latest-row pick (newest `computed_at`,
   `metric_value_id` tie-break). `directions` comes from the calc library's
   NEW metric registry (`headway_calc/registry.py`): `coverage:
   higher_is_better` ONLY; every reported metric explicitly `null`
   (sign-neutral), expansion is a reviewed calc-side act. Receipt
   affordance: every cell carries its `metric_value_id` verbatim.
2. **Counts** — `GET /dq/issues/counts?status=` →
   `{total, by_severity:{blocking,warning,info}, by_status:{open,owned,
   resolved}}`; `GET /safety/events/counts?month=&mode=` →
   `{total, by_classification:{major,non_major,not_reportable},
   unclassified, superseded}`. Both COMPOSE the exact list queries under
   the same filters (a card can never disagree with its table); zero
   buckets explicit. Deadlines urgency cards need no new endpoint: bucket
   the existing `GET /safety/deadlines` arrays client-side on `due_date`.
3. **Exports (design point 5)** — `format=csv|xlsx` on:
   `GET /metrics/values/export` (same filters as the list),
   `GET /reports/mr20/export?month=`, `GET /reports/ss50/export?month=`,
   `GET /sampling/plans/{id}/worksheet`. ONE row assembly feeds both
   formats (`headway_api/exports.py`); every XLSX cell is a TEXT cell
   (an Excel number cell is an IEEE double — it would corrupt exact
   NUMERIC strings); banner lines (NOT-REPORTABLE banners + caveats,
   preview disclaimer, simulated warning, worksheet requirement/retention)
   lead the CSV and form the XLSX's FIRST sheet ("Read first").
   Content-Disposition filenames: `headway-metric-values-…`,
   `headway-mr20-<month>-preview`, `headway-ss50-<month>-preview`,
   `headway-sampling-worksheet-<plan_id>`.
4. **`POST /sandbox/preview`** (design point 6) — body `{period_start,
   period_end, proposed: {<knob>: "<string value>"}}`; knobs =
   the four seeded NTD calc knobs + the two OTP-window ops knobs
   (`imbalance_threshold` is not a settings knob and is not previewable).
   Response: `{banner, persisted: false, period_*, proposed,
   settings_flow_note, ntd: {baseline_thresholds,
   baseline_threshold_sources, proposed_thresholds, inputs,
   metrics:[{metric, calc_name, calc_version, unit, scope, category,
   baseline:{value|null, blocked, findings[], detail}, proposed:{…},
   delta|null}]} | null, ops: {… + derivation} | null}`. Baseline = the
   CURRENT audited settings; both variants computed over the SAME loaded
   inputs; findings are surfaced summaries, never dq rows.
5. **Branding v2 (design point 7)** — three new seeded keys (migration
   0027): `brand_chrome_header_bg`, `brand_chrome_header_fg`,
   `brand_chrome_accent`; values `#rrggbb` or `unset` (default; `unset`
   turns the theme off). `PUT /settings/{key}` runs the SAME WCAG math
   pairwise (fg on bg ≥ 4.5:1, accent on bg ≥ 4.5:1) against the values
   that WOULD result — no single-key sequence can reach an unreadable
   header; refusals name the pair and the measured ratio in plain
   language. `GET /branding` (public) now serves
   `chrome: {header_bg, header_fg, accent} | null` — non-null ONLY when
   all three are set — plus `chrome_note` restating the standing
   dark-mode limitation (a theme not validated for a mode does not apply
   there — stated, never silent).

**The sandbox persistence decision (open question resolved, documented):**
EPHEMERAL. The ops-tagged-rows alternative was rejected as the larger and
less honest design: `headway_calc.persist` derives `category` from the calc
registry — never from a caller — precisely so figures cannot be re-labeled,
and persisting NTD-calc previews as 'ops' would have broken that rule. The
runner gained bounded READ-ONLY entry points (`preview_period`,
`preview_ops_period`) because composition genuinely cannot serve: both real
entry points durably route findings and persist values BY DESIGN
(fail-loudly-first), and doctoring a connection to swallow their commits
would be dishonest. The no-write guarantee is pinned by test (zero INSERTs,
zero commits) and live-verified below; nothing a preview produces exists
anywhere certification can reach, and the 0024 CHECK stands behind the real
ops runner's rows (attack-proven below).

**Deviations from the handoff's letter (reported, not absorbed):**
- Deltas are computed server-side as EXACT Decimal differences of the two
  served strings ("no new computation" read as: no new FIGURE computation —
  the cells themselves are verbatim persisted rows; a delta is a
  never-persisted comparison affordance, labeled as such in `delta_note`,
  exactness pinned by test). If the frontend prefers to render its own, the
  verbatim cell strings are all there.
- Counts are sibling GET endpoints rather than a `?counts=` param on the
  lists (one response model per route; same queries composed, so no drift).
- No server-side CSV existed for mr20/ss50/worksheet before this wave; the
  byte-equality rule is honored by generating BOTH formats from one grid
  and pinning XLSX==CSV cell-for-cell in tests + live diffs. The web's
  existing client-side monthly CSV stands; the server metrics export
  mirrors its disclaimer/columns and ADDS scope, category and
  metric_value_id (provenance travels in every export).
- Ops preview covers otp_v0 only — headway_adherence_v0 takes no policy
  knob, so a sandbox cannot move it (stated in the response contract).

## Outputs — backend evidence (2026-07-15, working tree at 1707a8f)

**Suites (grew):** calc `506 passed` (was 496: +7 preview, +3 registry);
api `245 passed` (was 202: +9 compare, +8 counts, +12 exports, +9 sandbox,
+5 chrome; existing branding/settings tests extended); db static
`25 passed` (was 24: +1 for 0027). Commands: the README-documented
`python3 -m pytest tests/ -q` per service; outputs captured this session.

**License gate GREEN with openpyxl:** `LICENSE GATE: PASS — 213
dependencies conform to ADR-0001 Amendment 1` (openpyxl 3.1.5 → `MIT
License PASS`; recorded in services/api/pyproject.toml). Local-env note:
the green run required the gate's own documented GOROOT workaround for
go-licenses (script docstring) and temporarily removing the gitignored
design-sync self-symlink `web/node_modules/web -> ..` (the node scanner
reports it as an unknown-license package "web"; restored immediately —
`ls -la web/node_modules/web` → `web -> ..`). Both are environmental; CI
is unaffected.

**openapi.json regenerated (drift gate):** `scripts/export_openapi.py` →
39 paths incl. the 8 new: `/metrics/compare`, `/metrics/values/export`,
`/dq/issues/counts`, `/safety/events/counts`, `/reports/mr20/export`,
`/reports/ss50/export`, `/sampling/plans/{plan_id}/worksheet`,
`/sandbox/preview`. Re-running the export is byte-stable.

**Migration 0027 applied live:** `python3 db/migrate.py` → `applying
0027_branding_chrome.sql ... ok`. psql (separate connection):
`SELECT setting_key, setting_value FROM app.settings WHERE setting_key
LIKE 'brand_chrome%'` → 3 rows, all `unset`, `updated_by=migration-0027`.

**Live demo API restarted, demo state intact:** env preserved from
`/proc/545366/environ` (session secret survives), new pid 603434,
`GET /openapi.json` 200 with all new routes; `dsteward`/`certifier` demo
logins worked immediately after restart.

**Compare, live (real figures, psql-verified beforehand):**
- Version comparison `metric=vrm`,
  `comparand=2026-07-14..2026-07-16@dr_vrm_v0:0.1.0` vs `@dr_vrm_v0:0.1.1`:
  `mode:DR` 517.42 → 512.75, `delta_vs_baseline=-4.67`; `mode:DR:tos:DO`
  274.52 → 269.85 (−4.67); PT/TX deltas `0.00` — exactly the 2026-07-13
  dr_vrm 0.1.1 hardening change (handoff 0013). NOTE: the handoff-0004 vrh
  v0.2/v0.3/v0.4 trio no longer coexists for one period in the live DB
  (psql: vrh has 0.2.0 only for [2026-07-09, 2026-07-11) and 0.4.0 for
  other periods), so the version-compare evidence uses the DR pair that
  does coexist; the period compare below covers vrh.
- Period comparison `metric=vrh`, `scope=agency`, comparands
  `2026-07-09..10 | 2026-07-10..11 | 2026-07-01..08-01`: 5364.54 →
  5389.40 (Δ 24.86) → 16326.89 (Δ vs baseline 10962.35, vs previous
  10937.49); every cell carried calc_name/version, certification_status
  and metric_value_id (receipts intact); `directions` served
  `{vrh: null, coverage: higher_is_better}`.

**Counts, live:** `/dq/issues/counts` → `{total: 35456, by_severity:
{blocking: 279, warning: 31869, info: 3308}, by_status: {open: 35210,
owned: 0, resolved: 246}}`; `/safety/events/counts` → `{total: 20,
by_classification: {major: 12, non_major: 4, not_reportable: 4},
unclassified: 0, superseded: 5}` — consistent with the live tables the
cards sit above.

**XLSX exports, live (downloaded and diffed cell-for-cell vs CSV):**
- `/metrics/values/export` July 2026: 429 data rows; banner sheet ==
  CSV banner lines (disclaimer + simulated warning); **0 cell
  mismatches; 0 non-text XLSX cells**.
- `/reports/mr20/export?month=2026-07`: 15 banner lines (NOT-REPORTABLE
  banner + caveats verbatim), 24 rows; fleet vrh `16326.89` with
  coverage `0.9061`; missing cells carry the package's explicit reasons;
  0 mismatches.
- `/reports/ss50/export?month=2026-07`: 13 banner lines, 6 cells incl.
  EXPLICIT ZERO ROWS (rail/subway/tram/unknown, `zero_event=yes`);
  bus/DO shows 2 injury events with their event_ids; 0 mismatches.
- `/sampling/plans/442a2e30-…/worksheet`: 50 unit rows with measured
  state; banner states `50 of 48 required — requirement met;
  the plan is estimate-ready`-class state line + retention note;
  0 mismatches. (Filenames per Content-Disposition, media types
  text/csv and openxml spreadsheet.)

**Sandbox preview, live — and the walls:**
- Row counts BEFORE: `computed.metric_values=429, dq.issues=35456,
  lineage.edges=15069758`.
- NTD preview [2026-07-09, 2026-07-10), proposed
  `{coverage_threshold: 0.90, layover_max_seconds: 600}` (43 s,
  733,312 positions loaded): baseline (audited settings, sources all
  `settings`) REFUSED vrm/vrh (coverage below 0.95; 800/1177 would-be
  findings surfaced, not routed) and pmt (the standing honest refuse);
  proposed un-blocked vrm at **50514.65 — exactly the persisted real
  figure for that period** — and vrh at 5344.27 (vs the persisted
  5364.54 under layover 1800: the knob's real impact); upt delta `0`.
- Ops preview, proposed `{otp_late_tolerance_seconds: 600}` (43 s,
  166,217 passages derived once): otp 51.53 → 70.95, `delta=19.42`,
  category `ops`, derivation accounting attached.
- Row counts AFTER both previews: `429 35456 15069758` — **identical.
  The preview changed nothing** (the calc-level pin:
  services/calc/tests/test_preview.py asserts zero INSERTs/commits).
- **Certify attack:** POST /certifications (as `certifier`) targeting the
  live otp agency row `5b43f678-…` → 409 (refused at the blocking-DQ gate
  first — 33 open blocking NTD issues; the route's ops refusal sits behind
  it, unit-tested). Direct SQL attack:
  `UPDATE computed.metric_values SET certification_status='certified'
  WHERE metric_value_id='5b43f678-…'` → `ERROR: new row … violates check
  constraint "metric_values_ops_never_certified"`; row re-read
  `uncertified`. The 0024 CHECK is the wall, proven by attack. Ephemeral
  previews have no id at all — certifying a fabricated id 404s
  (unit-tested).

**Branding v2, live (as `certifier`; then reset):**
- `brand_chrome_header_bg=#1f2328` → 200 (audit 754, old `unset` → new).
- `brand_chrome_header_fg=#767676` → **422**: "…the header text on the
  themed header background ('#767676' on '#1f2328') measures 3.48:1, and
  readable text needs at least 4.5:1 (WCAG 2.1 AA)…".
- `#ffffff` → 200 (15.80:1, audit 755); `brand_chrome_accent=#0b57d0` →
  **422** (2.47:1, names "active-item accent"); `#ffd700` → 200
  (11.26:1, audit 756).
- Re-whitening the bg (`#ffffff`) → **422** — the prospective-pair check
  blocks stranding the existing fg/accent.
- `GET /branding` (unauthenticated) served the complete
  `chrome: {header_bg: "#1f2328", header_fg: "#ffffff", accent:
  "#ffd700"}` + `chrome_note`; audit rows 754–756 psql-verified
  (actor `certifier`, old→new in detail). All three keys then reset to
  `unset` (200 each); `GET /branding` → `chrome: null` — the live demo
  stack is back to neutral Headway chrome.

**Docs:** services/api/README.md endpoints table extended (8 new rows +
settings/branding rows updated); services/calc/README.md gained the
preview-entry-point and direction-registry sections. No commits made; no
files under web/ touched; docs/reference/ not read.

## Outputs — frontend evidence (2026-07-14, working tree; web/ only)

Frontend half delivered: design points 1 (/compare cards + matrix), 2
(summary cards as filter toggles on /dq, the /safety events list, and the
deadlines panel), 3 (in-row progress bars in the sampling plans list), 4
(toasts + breadcrumbs shell-wide), 6 (/sandbox), 7 (themed chrome
application). Design point 5 (XLSX) is backend-only this wave — see the
gaps list below.

**What shipped (all under `web/`):**

- `src/views/CompareView.tsx` (+ route `/compare`, nav entry): metric +
  2–4 comparands (calc versions of one period, or one calc across
  periods; tick order sets the baseline, stated in the hint) → card row
  (value verbatim + unit, delta vs baseline and vs previous, per-mode
  subline) + detail matrix. Binding rules upheld and pinned by test:
  every cell's figure is a button opening the SAME `Receipt` component in
  a focus-trapped dialog; deltas render SIGN-NEUTRALLY (glyph + magnitude,
  muted both directions — `src/components/DeltaFigure.tsx`) unless
  `directions[metric]` from the calc registry says otherwise (then always
  with the word "better"/"worse", never color alone); simulated/ops/DR/
  pre-verification badges carry through cards AND matrix cells; a
  certified-vs-uncertified mix renders the server's
  `mixed_certification_note` verbatim and tags every figure; `delta_note`
  + `direction_note` render verbatim over the matrix; missing cells show
  `missing_reason` verbatim, never blank.
- `src/components/SummaryCards.tsx`: count cards with colored top border
  + label, each a real `<button aria-pressed>` filter toggle (pressed =
  check mark + fill + label — never color alone). Wired as: /dq severity
  cards (+ a Resolved status card), /safety classification cards (an
  event with no classification on file always stays visible — a gap is
  never hidden by a filter), deadlines urgency cards (overdue / due
  within 7 days / due later, bucketing the API-served due dates
  client-side per the backend response). Counts are workflow tallies that
  always cover the whole queue; filtered-out items are counted out loud.
- `src/components/RowProgress.tsx`: measured-vs-required per sampling
  plan in the plans list — value + label TEXT leads, meter echoes
  (useMeter, role pinned to "meter"), estimate-ready state visually
  distinct (success fill + "Ready to estimate" tag).
- `src/toasts.ts` + `src/components/Toasts.tsx`: ONE persistent
  `role="log"` aria-live=polite region in the shell; create/supersede/
  certify/resolve confirmations across /safety, /sampling, /dq, /certify
  and /sandbox push here. Deterministic lifetime — explicit dismiss or
  route change, never a timer.
- `src/components/Breadcrumbs.tsx`: receipt → lineage (LineageView),
  sampling plan → draw → measurements (per worksheet, uniquely labeled
  landmarks, excluded from the printed sheet), safety event → correction.
- `src/views/SandboxView.tsx` (+ route `/sandbox`, nav entry): the
  hard walls as rendered — the changes-nothing banner on every visit AND
  the server's own banner verbatim on every result; NO apply control
  anywhere (`queryByRole button /apply/i` pinned absent by test, before
  and after a preview); the server's `settings_flow_note` verbatim;
  knob editors read current values/descriptions/provenance verbatim from
  GET /settings (values stay strings end to end); the impact rail renders
  the ntd/ops sections with baseline-vs-proposed thresholds + sources,
  input counts, per-figure sides (value verbatim + "Preview — changes
  nothing" tag, or the stated refusal with every would-be finding title
  listed), and sign-neutral server-computed deltas.
- Themed chrome (branding v2): `Layout.tsx` applies `GET /branding`.chrome
  as `--chrome-*` custom-property overrides + `data-chrome="on"` in the
  LIGHT theme only; dark keeps the neutral tokens (the served chrome_note
  rule; also stated in the branding room via `copy.branding.chromeDarkNote`).
  Neutral default when unset/predating APIs; charts never read chrome
  tokens; reverting to 'unset' restores neutral (pinned by test + live).

**Contract reconciliation (mock-first, then the export):** built against
typed mocks from the handoff description while the backend was in flight;
when `/metrics/compare`, `/sandbox/preview`, and branding v2 appeared in
the regenerated `services/api/openapi.json` (same day), `src/api/types.ts`,
`client.ts`, both views, fixtures and tests were reconciled against the
export. Corrections made in reconciliation (none silent): comparand token
form (`<start>..<end>@<calc>:<version>`, not the mock's calc-first order),
sandbox body key `proposed` (not `settings`) and the sectioned
ntd/ops response with `PreviewSide`s replacing the mock's flat rows (and
with it: NO receipt door on preview figures — they are ephemeral by the
backend's documented persistence decision, so there is no persisted row to
walk; the impact table names calc + version instead), chrome field names
(`header_fg`/`accent`, ONE color set, no dark variant), `directions` as a
map with an explicit null for sign-neutral metrics.

**Suite / build / gates (2026-07-14):**

```
npm test -- --run        Test Files 25 passed (25); Tests 145 passed (145)
                         (was 20 files / 116 tests before the wave; every
                          new view test asserts zero axe violations,
                          including with the receipt dialog open)
npm run build            tsc -b + vite clean; 1328 modules
npm run check:contrast   All 71 token pairs meet WCAG 2.1 AA (18 new pairs
                         registered: summary-card top borders, toast
                         border, delta better/worse text, ready progress
                         fill, sandbox note border — light + dark)
npm run lint             clean
```

**Live click-through (2026-07-14, headless Chrome via CDP against the live
Compose stack — vite on localhost:5173, API on localhost:8000; SPA nav only
after login per the in-memory token; screenshots `shots-0017/01…12*.png` in
the session scratchpad):**

1. Login as dsteward → /compare: periods mode over REAL figures —
   vrh_v0 0.4.0, 2026-07-09..10 (baseline, agency 5364.54 h) vs
   2026-07-10..11 (5389.40 h) → card row + matrix rendered with the
   sign-neutral "▲ 24.86 more than the baseline" (the server's exact
   delta), pre-verification tags on both, the mode:rail missing cell
   stated verbatim ("A missing figure is shown as missing, never
   invented."), and a matrix cell's Receipt opened live (verbatim FTA
   quotes + walk link) [01–03].
2. /dq: summary cards over the real queue — 33 blocking open / 31,869
   warnings open / 3,308 info open / 246 resolved; pressing "Blocking
   open" filtered to 279 blocking issues with the showing-line stating
   "Showing 279 of 35,456 issues" [04–05].
3. /sandbox: proposed coverage_threshold 0.95 → 0.90 for 2026-07-09..10 →
   a REAL ephemeral recompute (733,312 positions read); the rail showed
   vrm_v0 0.2.0 refusing under today's settings (verbatim would-be
   findings) beside 50514.65 under the proposal, every preview figure
   tagged "PREVIEW — CHANGES NOTHING", the server banner + settings-flow
   note verbatim, and the toast confirmation in the live region [06–07,
   12]. Verified changes-nothing from the outside: GET /metrics/values
   served 429 rows and GET /dq/issues 35,456 rows both BEFORE and AFTER
   two live previews (counts taken via curl either side).
4. Themed chrome, applied AND reverted through the audited settings flow
   (PUT /settings/brand_chrome_* as certifier): the server first REFUSED
   accent #ffd24a on #1a5fb4 verbatim ("measures 4.36:1, and readable
   text needs at least 4.5:1") — the WCAG wall observed live — then
   accepted #ffe9a8; the shell applied the chrome in light
   (`--chrome-*` set, data-chrome=on), kept dark NEUTRAL (chrome
   properties absent with data-theme=dark), and after reverting all three
   keys to 'unset' rendered the neutral Headway chrome again [08–10].
   The live DB is back at 'unset'.
5. Breadcrumbs live: /metrics → a real figure's lineage renders
   "Metrics › Figure cad242bd… › How this number was made" [11].

**Live findings (found by the click-through, fixed in this wave):**

- **/dq scale**: the live queue holds 35,456 issues and the page drew a
  card for every one — the tab froze (the CDP session died mid-render).
  Fixed with a LOUD render cap (first 200 matching cards drawn; banner
  states "Only the first 200 of N matching issues are drawn… Nothing is
  dropped"; counts always cover the whole queue; filters narrow). Pinned
  by test (250-issue fixture → 200 articles + both numbers stated).
- **Sign-in link on themed chrome**: signed out, the header's "Sign in"
  link kept the accent-blue color on the themed blue header bar —
  unreadable. Fixed: session-info links take the server-verified
  header_fg on a chrome theme (neutral chrome keeps the accent link).
  Re-verified live [08].

**Honest gaps / notes for the orchestrator:**

- **Counts endpoints not consumed (yet).** /dq and /safety cards keep
  client-side tallies computed from the same full-list response the page
  renders — consistent with their tables by construction. The sibling
  `GET /dq/issues/counts` / `GET /safety/events/counts` become necessary
  the day the lists paginate; note the /dq cards count per-severity OPEN
  (open+owned) issues, which the counts endpoint's independent
  by_severity/by_status buckets do not directly serve — worth a shape
  tweak whenever pagination lands.
- **XLSX exports (design point 5) have no frontend room this wave.** The
  existing client-side CSV buttons stand unchanged; wiring the new
  `/…/export?format=xlsx` endpoints into the report/metrics/sampling
  pages is a small follow-up increment (download link per surface).
- **The audited settings flow has no UI room for calculation knobs.**
  The sandbox names the flow verbatim (server text + its own plain
  statement) and deliberately hosts no apply control, but
  `PUT /settings/{key}` for calc knobs is API-only today — the handoff's
  "link to the existing audited settings flow" cannot be a literal link
  until a settings room exists (only /settings/branding exists, and it is
  branding-scoped). Recorded rather than papered over with a misleading
  link.
- **Write-flow toasts/breadcrumbs were verified against typed mocks**, not
  live: exercising the safety supersede and sampling create/draw/measure
  paths live would write records into the live agency DB, which this wave
  avoided. The sandbox-preview toast (a true no-op) covered the toast
  region live [12]; the rest is pinned by the suite (safety/sampling/dq/
  certify toast assertions + breadcrumb tests).
- Two long-running tests (safety record, sampling estimate walkthrough)
  carry explicit 15 s vitest timeouts — they sat at the 5 s default's edge
  under full-suite load on this box.

### Addendum — export buttons wired to the server endpoints (2026-07-14, working tree; web/ only)

Design point 5's frontend gap is closed: a compact CSV + XLSX export
control (`src/components/ExportButtons.tsx` — house buttons, group role,
visually-hidden per-button surface names so several controls on one page
stay uniquely labeled) now sits on all four surfaces, calling the backend
wave's export endpoints through the authenticated client (new
`blob` mode in `src/api/client.ts` `request()`; the saved file is the
response body BYTE FOR BYTE under the server's Content-Disposition
filename, via the extracted `src/download.ts` `saveBlob` — the MR-20 JSON
download now shares it, behavior unchanged). Success confirms through the
shell toast region (`role="log"`, deterministic lifetime), naming the
saved file; an API refusal renders verbatim as a local alert, no toast.

- **/metrics** → `GET /metrics/values/export?format=` (unfiltered, like
  the table).
- **/reports/monthly, ridership preview** → the same endpoint with the
  picked month's `period_start`/`period_end`. This REPLACED the
  client-side CSV assembly (`src/reports/csv.ts` deleted).
  **Differences from the retired client CSV, stated out loud** (also in
  the control's always-visible note, `copy.report.export.note`):
  1. Columns: the server mirrors the client's nine
     (`metric,unit,period_start,period_end,value,calc_name,calc_version,
     certification_status,simulated_data`) and appends `scope`,
     `category`, `metric_value_id` (scope inserted after `period_end`,
     the other two at the end).
  2. Rows: the client file held only the page's three ridership metrics
     (vrm/vrh/upt); the server export covers EVERY figure computed for
     the month — ops metrics (flagged by `category`), DR scopes,
     coverage — same disclaimer first, plus the server's simulated-data
     banner line when any row is simulated.
- **/reports/monthly, MR-20 section** →
  `GET /reports/mr20/export?month=` beside the unchanged byte-for-byte
  JSON package download.
- **/safety deadlines panel (the S&S-50 monthly surface)** →
  `GET /reports/ss50/export?month=` for the API-served `deadlines.month`
  (never a client guess), with a note stating the file's coverage
  (explicit zero-event rows included).
- **/sampling, per plan beside the print button** →
  `GET /sampling/plans/{id}/worksheet?format=`. Note: the file covers
  every draw of the plan in one worksheet (requirement + retention note
  leading), where the printed sheets are per-draw.

**Suite / gates (2026-07-14):** `npm test -- --run` → Test Files
26 passed, **Tests 150 passed** (was 25/145: −2 retired client-CSV tests,
+1 replacement pinning the swap — old button gone, note shown, request
params, byte-identical save, toast — and +6 in `src/test/exports.test.tsx`
covering all four surfaces, both formats, the bearer header, the
Content-Disposition filename, the error path, each with zero axe
violations). `npx tsc -b` + `npm run build` clean; `npm run lint` clean;
`npm run check:contrast` all 71 pairs pass (no new color pairs — the
control reuses house button tokens). Test harness: `mockApi` gained
`rawBody`/`headers` on `MockedResponse` for binary download routes.

**Live verification (2026-07-14, API on 127.0.0.1:8000, as `dsteward`):**
one surface, both formats — `GET /metrics/values/export` for
2026-07-01..2026-07-31 (the view's derived month period): CSV 11,311
bytes, 2 banner lines (disclaimer + simulated warning) + header + 72 data
rows, `text/csv; charset=utf-8`,
`filename="headway-metric-values-2026-07-01-2026-07-31.csv"`; XLSX 11,251
bytes, valid workbook with "Read first" banner sheet (2 rows) + data
sheet (73 rows incl. header = the same 72 data rows), every cell an
inline TEXT string (zero numeric cells), openxml media type and matching
filename. The other three surfaces were mock-verified by the suite only
(their live flows write nothing, but this pass stayed read-only and
UI-through-live was not click-driven). No commits made.
