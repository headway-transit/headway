# Headway web UI

The certification web UI for the walking skeleton (ADR-0009): sign in, read
computed VRM/VRH figures, drill any figure down to the raw records that
produced it ("How this number was made"), work the data-quality queue, and —
for a certifying official — perform the attested certification action.

Built against the exported API contract at `services/api/openapi.json`
(Headway API 0.1.0). Vite + React + TypeScript, React Router, plain semantic
HTML with hand-rolled CSS tokens. Per handoff 0007 the accessible foundation
is **React Aria** (Adobe, Apache-2.0): new components (the Receipt's coverage
meter, the lineage view toggle) use `react-aria` / `react-aria-components`;
existing hand-rolled patterns migrate opportunistically, not big-bang.

## Non-negotiables encoded here

- **A figure is never computed or edited client-side.** `MetricValue.value`
  is a decimal **string** end to end (`src/api/types.ts`); it is rendered
  verbatim and never passed through `parseFloat`/`Number`.
- **Every figure links to its provenance** (`/metrics/:id/lineage`).
- **API error messages are shown verbatim** — the API writes plain-language
  errors by design; the UI never softens a refusal.
- **Role gating in the client is UX only.** The API enforces authorization on
  every request; hiding a button is never security.
- **Fail loudly:** DQ issues are listed until resolved, blocking issues are
  visually prominent, and a certification refusal (409) is shown word for
  word with a link to the DQ queue.

## Run

```sh
npm install
npm run dev        # dev server on http://localhost:5173
npm run build      # type-check (tsc -b) + production build to dist/
npm test -- --run  # vitest + Testing Library + axe-core checks
npm run check:contrast  # verify the WCAG contrast of every color token pair
npm run extract:quotes  # regenerate src/regulatory/quotes.json from the tracker
```

### Regulatory quotes (`src/regulatory/quotes.json`)

"The FTA rule inside the number" (handoff 0007, pillar 1):
`scripts/extract-quotes.mjs` copies the VERBATIM FTA manual quotes from
every `## Verified …` section of `services/calc/REGULATORY_TRACKER.md`
("Verified definitions", S&S, MR-20, PMT, Sampling Manual, Demand Response —
swept by that heading convention since the 2026-07-13 convergence; the
section→calc mapping lives in the script's `calcNamesForHeading`, and a
heading naming its calc inline, e.g. "calc upt_v0", maps with zero config)
into a static, versioned JSON keyed by `calc_name`. Quotes
are never paraphrased or generated; the only in-quote cleanup is unwrapping
the tracker's own `**` markdown emphasis, and text after a bullet's `NOTE:`
(tracker meta-commentary ABOUT the manual's wording) is never quoted. The
script fails loudly (non-zero exit) if any calc in the tracker table lacks
quotes, and `src/test/quotes.test.ts` fails the suite if any calc named in
the fixtures — or any quote snippet the `/safety` receipts and deadline
citations depend on (`src/regulatory/safetyRules.ts`) — lacks quotes.
Regenerate after the NTD/Compliance Engineer updates the tracker; never
hand-edit the JSON.

### API base URL

Set `VITE_API_BASE_URL` to the API origin (no trailing slash), e.g.:

```sh
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

Unset, requests go to the same origin (for co-hosting or a dev proxy).

### Sessions

The bearer token from `POST /auth/login` is held in **sessionStorage**
(`src/auth/session.ts`, key `headway-session-v1`): it survives a page reload
and dies with the tab. It was in memory only until 2026-08-03, when a reload
signed you out — an annoyance on a desktop and unusable on a phone, where
pull-to-refresh is a gesture people make by accident.

What that trades, stated plainly: an XSS payload on this origin could read the
token. It is bounded by the 30-minute expiry, by the server re-reading the
account on **every** request (so a stolen token dies the moment the account is
deactivated, rather than running to expiry), and by the fact that an XSS can
already act as the user for as long as the page is open. Nothing is written to
localStorage, which would outlive the tab and every other tab.

The hardening increment is unchanged — a server-set `httpOnly`,
`Secure`, `SameSite` cookie session, which removes the token from JS reach
entirely. Any 401 clears the session and returns you to `/login`.

## Views

| Route | What it does |
|---|---|
| `/login` | Local-account sign-in (ADR-0011). Failures announced via `role="alert"`, verbatim. Lands on `/today`. |
| `/today` | The **role-aware briefing home** (handoff 0021, design point 1; `src/views/TodayView.tsx`) — the post-login landing ("/" redirects here; the dashboard keeps its nav place). Briefing cards composed CLIENT-SIDE from existing endpoints, including the counts endpoints (`GET /dq/issues/counts` — open + owned for the unresolved severity split plus ONE unfiltered whole-queue call; handoff 0023 rewrote the endpoint as a SQL GROUP BY, 4.8–5.9 s → 33–49 ms live, so the 0021 per-status-only workaround is deleted per handoff 0024 #3; `GET /safety/events/counts`). Composition: certifying official leads with certification state (month tally of uncertified figures + blocking-issue count + certifications on record) and safety deadlines; data steward with the DQ queue (open/owned/blocking/attested/resolved — counted server-side, never downloaded) and safety; report preparer with monthly-report readiness (which of VRM/VRH/UPT/VOMS have a figure this month — a workflow tally, never a sum) and sampling progress (house RowProgress per plan); viewer goes straight to the figures. Everyone gets KPI cards (latest VRM/VRH/UPT verbatim; the figure IS a button disclosing its full Receipt inline; delta vs the previous period SERVER-computed via `GET /metrics/compare` and rendered sign-neutrally through DeltaFigure; a first figure's missing delta is stated) and ops cards (OTP + cvh, always badged, same receipt door). Binding: every number keeps its receipt door (figures → Receipt + lineage; tallies → the exact list they were counted over); empty cards are warm honest statements, never invented urgency; per-slice skeletons while loading; per-slice errors verbatim, unanimated. |
| `/map` | The **living system view** (handoff 0024, design point 1; `src/views/MapView.tsx`; any signed-in role). MapLibre GL JS (BSD-3-Clause, license-gate verified) drawing ONLY self-hosted data: stops + **schematic** route lines from `GET /geometry/stops|routes` (the legend renders the server's `geometry_note` verbatim — straight lines between stops, never street geometry we don't have), live vehicles from `GET /ops/vehicles/latest` polled every 20 s. **Zero external requests in BOTH basemap states** (handoff 0027): with no basemap the inline style has no tile sources, no `sprite`, no symbol layers, and its one `glyphs` URL points at this installation's own vendored fonts — nothing is fetched at all; with the admin-downloaded self-hosted basemap present (`/basemap/region.pmtiles`, detected at runtime by HEAD + a ranged magic-bytes read), OpenStreetMap streets render UNDER the schematic/stops/vehicle layers from same-origin byte-range reads, with "© OpenStreetMap contributors · Protomaps" visible on the canvas and in the legend (ODbL), light + dark flavors wired to the theme toggle, labels in the one vendored Noto stack, POI icons deliberately absent (v0 limitation, stated in the legend). Absent → certifying officials get one quiet teaching line naming `install.sh --download-basemap`; a file that answers without byte-range support is a plain-language alert, never silently ignored. Ops-badged surface with the envelope's `ops_note` verbatim. The staleness chip is honest: "Live — newest position at T" only while the newest position is within the 300 s live window; otherwise "No vehicle positions in the last N" (server-timestamp math) with the server's own note verbatim. A window selector (5 min / 1 h / 24 h → `max_age_seconds`) shows last-known positions without ever faking freshness; dots JUMP on new reports (no positional tweening for anyone — gliding would draw positions nobody reported); per-vehicle popover + accessible list table (cap 100, stated) carry route/trip context, verbatim `age_seconds`, source, and the SIMULATED badge. Code-split (React.lazy) so /today first paint never pays for MapLibre. |
| `/dashboard` | Operational dashboard (handoff 0008, pillar B; any signed-in role). Hero stat tiles show the latest **certified** VRM/VRH/UPT verbatim (SimulatedBadge where flagged, provenance link on every tile). Four hand-rolled SVG charts follow the dataviz discipline: UPT line with crosshair + tooltip; VRM & VRH as **small multiples** (one axis each — never dual-axis, asserted structurally in tests); coverage-over-time from the detail JSONB with the coverage threshold as a dashed reference line; unresolved DQ issues as thin stacked bars in reserved status colors with icon + label. Every chart has a keyboard reader (arrow keys walk the points), direct end labels, and a table-view toggle (the WCAG-clean equivalent carrying provenance links). Series colors come only from the validated `--series-*` tokens — never brand colors. **Audience lenses** (handoff 0024, design point 2): a lens bar with three named presets — Board (quarter), Executive (month, default), Operations (day, ops cards first) — that are LENS CONFIGURATIONS only (the intro says so; the server's `grouping_note` renders verbatim): they set the `GET /metrics/history` `bucket` param and the section order, never a number. Hero tiles carry **sparkline trends** where history exists: every point is a persisted figure served verbatim (a real button, one click to its full Receipt); a calendar bucket with no figure is a GAP — the line breaks and the absence is stated in words, never interpolated; certified points differ by shape + words, never color alone. |
| `/settings/branding` | Agency branding (handoff 0008, pillar C; certifying official). Display name, two brand colors with live preview, and logo upload (SVG/PNG ≤ 512 KiB, multipart to `POST /branding/logo`). The **server** refuses colors that fail WCAG AA against the app surfaces (plain-language 422, surfaced verbatim). Saved branding restyles CHROME only: the shell fetches `GET /branding` on load, shows the display name + logo in the header, and overrides `--brand-primary`/`--brand-accent`; the dark theme pins its own accent (the server guardrail covers light surfaces only), and charts never read brand tokens. |
| `/metrics` | Computed values table: metric, unit, period, value (verbatim string), calculation name+version, certification status. Calc versions below 1.0.0 carry a "Pre-verification" tag and a plain-language banner (they are marked PRE-VERIFICATION in `services/calc/REGULATORY_TRACKER.md` — not certifiable figures yet). EVERY figure's "Details" opens its **Receipt** (`src/components/Receipt.tsx`): story line, coverage meter + exclusions, the verbatim FTA rule + citation, flags, and the walk to raw records. Read-only: the certify flow moved to `/certify`; certifying officials see a plain note linking there. |
| `/calc-runs` | The **calculations room** ("Compute figures", handoff 0026; `src/views/CalcRunsView.tsx`). Ask the server to run the deterministic calculation service over one half-open period (month presets + custom range) via `POST /calc/runs` (data_steward+ — nav link + form gated as UX only, the API enforces the role) and read every run's honest outcome from `GET /calc/runs` (any signed-in role; viewers get the read-only surface with plain words about who computes). Binding rules: the page never computes a number — every figure, count, and id is the runner's own string served verbatim; **refusals are first-class** (status "Refused — figures withheld", the per-calc outcomes name the EXACT blocking findings and link them straight into `/dq?issue=<id>`, and a newest-run refusal shows the house-voice teaching block walking to the DQ queue); **no fake progress** (a live run shows "Running since HH:MM:SS UTC" only, polled every 5 s; no bar, no percentage, nothing animated); the single-flight 409 and the server's staleness note render verbatim at the control; persisted outcomes link to `/metrics` and the figure's lineage receipt. The old developer CLI line is gone from every user surface (metrics/dashboard/today empty states now door here or state who computes). |
| `/compare` | The **comparison surface** (handoff 0017, design point 1; `src/views/CompareView.tsx`): pick a metric and 2–4 comparands — calculation versions of one period, or one calculation across periods — → a card row (big value verbatim, delta vs the baseline and vs the previous comparand, per-mode subline) and a detail matrix (rows = scopes, columns = comparands). Binding rules upheld: every cell's figure is a button opening the SAME Receipt as every other surface (focus-trapped dialog); deltas are SERVER-computed exact-decimal strings rendered **sign-neutrally** (glyph + magnitude, muted for both directions) unless the response's calc-registry `directions` entry defines better/worse (coverage only today — and then always with the word, never color alone); simulated/ops/DR/pre-verification badges carry through; a certified-vs-uncertified mix renders the server's label-both note verbatim and tags every figure. The comparand vocabulary is enumerated client-side from `GET /metrics/values` (a workflow enumeration); figures and deltas come verbatim from `GET /metrics/compare` — this page never subtracts two figures. |
| `/sandbox` | The **settings sandbox** (handoff 0017, design point 6; `src/views/SandboxView.tsx`): what-if modeling behind the honesty walls. Propose values for the previewable policy knobs (current values + descriptions verbatim from `GET /settings`), pick a period, and `POST /sandbox/preview` recomputes both variants over the same recorded data — EPHEMERALLY (the API's `persisted` is constant false; nothing is written anywhere, so preview figures deliberately have no receipt/lineage door). "Modeling preview — changes nothing" banners on every visit AND on every result (the server's own banner verbatim); the impact rail shows baseline vs proposed per figure with every would-be finding listed (refusals stated, never blank) and sign-neutral server-computed deltas; there is **no apply control anywhere** — the server's settings_flow_note names the separate audited settings flow verbatim. |
| `/metrics/:id/lineage` | "How this number was made": the provenance tree from `GET /metrics/values/{id}/lineage`. Carries a breadcrumb trail (handoff 0017 #4): Metrics → figure → this page. Default is the **lineage graph** (`src/components/LineageGraph.tsx`) — a hand-rolled accessible SVG flow (figure → processing steps → raw records; raw tier collapsed to a count node, expanding 20 at a time; arrow keys move within/between tiers, Enter toggles). A "Text view" toggle is always visible and renders the FULL nested-list tree (every node, complete record ids) — the graph is progressive enhancement, never the only path. **Since handoff 0035 the raw leaves OPEN** (`src/components/RawRecordInspector.tsx`): a UAT auditor reached this page, hit a wall of hashes labelled "the end of the trail" and said *"It doesn't really provide any data to validate or verify."* Each leaf now discloses the record's LABEL (source, who collected it, when it arrived, size, whether it could be read on arrival — absent values rendered absent), a **Verify integrity** action whose verdict is rendered in the server's own words (a pass is a `role="status"`; a MISMATCH is a `role="alert"` panel stating BOTH fingerprints, naming the blocking DQ finding it raised and linking to it — loud by heading, icon, border and text, never by colour), an expandable **bounded preview** whose cap is stated BEFORE the data (a GTFS-Realtime frame becomes its real vehicles at their real coordinates at that minute; a contract CSV becomes its own header + first rows; a vendor export becomes lines verbatim with NO invented column names), and the exact bytes to download. The **hash stays visible, demoted to the footnote it should always have been**. Withheld payloads (paratransit — rider addresses) explain the refusal and keep the label and the integrity check: the chain of custody is never broken, only the window is closed. View parity holds — a raw node in the graph opens the SAME inspector in a panel beneath it. Leaves open ON DEMAND, not with the tree: one live VRH figure has 1,138 raw leaves, and fetching a label for each on load would be the handoff-0030 mistake in a new costume. |
| `/reports/monthly` | Monthly ridership preview: VRM/VRH/UPT for a picked month, verbatim, with certification status, coverage summary, per-row Receipt, provenance links, simulated-data banner, and CSV export of the exact served strings. |
| `/safety` | The **Safety & Security module** (handoff 0010, design point 5; `src/views/SafetyView.tsx`), typed against `services/api` routers/safety.py exactly. Three rooms: a **deadlines panel** (`GET /safety/deadlines`) with API-computed due dates — S&S-40 per open major event, S&S-50 per operated mode **including zero-event rows** — each rule shown as the verbatim tracker quote + page citation, urgency as text + icon + color (never color alone; the only client date math is days-until-the-served-date); a plain-language **entry form** (`POST /safety/events`, data_steward+; "Was anyone taken directly from the scene for medical care?", never "injury threshold") with rail-only questions disclosed only for the classifier's own rail-mode set, client-side validation mirroring the contract, and the returned verdict rendered as a **classification receipt** (the sscls_v0 classifier's summary and per-threshold sentences verbatim, plus the verified manual quote per token via the extract-quotes pattern; unknown tokens and unmapped quotes stated loudly, never hidden); and the **events list** with classification chips (major/non-major/not reportable), per-event receipts, and the append-only **correction flow** (`POST /safety/events/{id}/supersede`, required audit reason) — the original stays visible, struck and linked to its replacement, never hidden. Honest-scope banner on every visit: alpha, no NTD e-filing. The page never classifies an event; `property_damage_usd` is a decimal string end to end. |
| `/dq` | Data-quality queue: severity as text + icon + color (never color alone), status/owner/description, blocking issues prominent with their consequence stated. Since handoff 0024 the queue-at-a-glance cards are SERVER counts (`GET /dq/issues/counts`, milliseconds since 0023) painted while the full list downloads, and they are refetched after every resolve/attest — recounted, never client-adjusted. Resolve action (required resolution note) appears for data stewards and above. |
| `/certify` | The **certification cockpit** (handoff 0007's deferred pillar): one screen showing exactly what a signature covers. Nav entry and controls appear only for the certifying official (UX only — the API enforces the role). Anatomy, in order: month/year period picker → every figure of the period as a full Receipt with a labeled consent checkbox ("Certify …") → a blockers panel counting open blocking DQ issues (reason mirrors the API's 409 wording; certify disabled while any exist; link to `/dq`) → an unmissable warning + separate acknowledge checkbox whenever any selected figure is simulated or pre-verification (acknowledgement clears on any selection change) → the attestation dialog. |

The certify flow (`src/views/CertifyView.tsx`): tick figures against their
receipts → "Certify selected figures" → a focus-trapped `aria-modal` dialog
that restates **exactly** which figures (metric, value verbatim, period,
calculation + version, each with its provenance link) are being attested →
required attestation statement → `POST /certifications`. The API is the
system of record: success shows the certification id and audit event
reference the API returned verbatim, and figures + blockers are re-read from
the API rather than assumed. A 409 refusal is shown word for word with the
`/dq` link.

## Accessibility (WCAG 2.1 AA)

### Color tokens

All pairs are verified by `scripts/check-contrast.mjs` (run
`npm run check:contrast`; it exits non-zero on any failure). Current output:

| Pair | Ratio | Minimum |
|---|---|---|
| body text `#1f2328` on page `#ffffff` | 15.80:1 | 4.5:1 |
| body text `#1f2328` on surface `#f6f8fa` | 14.84:1 | 4.5:1 |
| muted text `#57606a` on `#ffffff` | 6.39:1 | 4.5:1 |
| link/accent `#0b57d0` on `#ffffff` | 6.39:1 | 4.5:1 |
| button text `#ffffff` on accent `#0b57d0` | 6.39:1 | 4.5:1 |
| blocking text `#9f1b1b` on `#fdeaea` | 6.85:1 | 4.5:1 |
| warning text `#664b00` on `#fff3d1` | 7.39:1 | 4.5:1 |
| info text `#1d4e89` on `#e7f0fa` | 7.29:1 | 4.5:1 |
| certified text `#1c632f` on `#e8f5eb` | 6.50:1 | 4.5:1 |
| focus outline `#0b57d0` on `#ffffff` (non-text) | 6.39:1 | 3:1 |
| input border `#57606a` on `#ffffff` (non-text) | 6.39:1 | 3:1 |
| severity icons on their badge backgrounds (non-text) | ≥ 6.85:1 | 3:1 |
| muted + accent text on surface `#f6f8fa` (receipt cite, graph) | 6.00:1 | 4.5:1 |
| meter fill / graph strokes (non-text) | ≥ 6.00:1 | 3:1 |

jsdom cannot evaluate color contrast, so the axe runs in the test suite
disable only the `color-contrast` rule and this script is the contrast
verification. Severity is additionally encoded by distinct icon **shapes**
(octagon/triangle/circle) plus text — never color alone.

### Theming (handoff 0008, pillar A)

Two deliberately selected token sets: light (`:root`) and dark
(`:root[data-theme="dark"]`) in `src/styles.css`. The effective theme is the
explicit user choice persisted in `localStorage` (`headway-theme`), else
`prefers-color-scheme`; `index.html` stamps `data-theme` inline before first
paint and `src/theme.ts` re-resolves it (and follows OS changes while no
explicit choice exists). Every dark pair is in `check-contrast.mjs` and must
pass alongside the light set.

Chart series colors (`--series-1/2`, dark-stepped per mode) are validated
with the dataviz palette validator against each mode's chart surface
(`#ffffff` light / `#161b22` dark); chart status colors are reserved for
severity and always ride with icon + label. Brand overrides (`--brand-*`,
from `GET /branding`) are chrome only — the server refuses any brand color
under 4.5:1 on either light surface, dark mode pins its own accent, and
charts never read brand tokens.

### Keyboard map

- `Tab` — every interactive element is reachable in DOM order with a visible
  focus ring (`:focus-visible`, 3px accent outline).
- First `Tab` on any page — "Skip to main content" link.
- Route change — focus moves to `<main>` so the new page is announced.
- Certify cockpit: `Tab` runs picker → per-figure consent checkboxes (each
  receipt's links in between) → the blockers panel's `/dq` link → the
  acknowledge checkbox (when warnings apply) → the certify button; `Space`
  toggles the checkboxes; `Enter` on "Certify selected figures" opens the
  dialog. The disabled button is skipped until its stated blockers /
  acknowledgement are cleared.
- Certify dialog — focus moves in on open, `Tab`/`Shift+Tab` are trapped
  inside, `Escape` closes, focus returns to the opening button (APG dialog
  pattern, hand-rolled in `src/components/Modal.tsx`).
- Lineage graph — roving tabindex over the SVG nodes: `↑`/`↓` move within a
  tier, `←`/`→` move between tiers, `Enter`/`Space` expand or collapse the
  raw-records group and page in 20 more; focus is drawn as a 3px accent
  stroke on the node. "Graph view"/"Text view" are real toggle buttons
  (`aria-pressed`).
- Lineage text view — each node with inputs has a toggle button
  (`Enter`/`Space`) carrying `aria-expanded`.
- Receipt — "Details" buttons carry `aria-expanded`; the coverage meter is a
  `role="meter"` with `aria-valuetext` announcing the verbatim percent
  string.
- DQ — "Resolve: …" buttons open an inline form; the resolution textarea is
  labeled and described.

Status messages use `role="status"`; errors use `role="alert"` and quote the
API verbatim.

### UI wave (handoff 0017): summary cards, toasts, breadcrumbs, chrome

- **Summary-card filter toggles** (`src/components/SummaryCards.tsx`): the
  count cards above /dq (severity), the /safety events list
  (classification), and the deadlines panel (urgency) ARE the filters —
  real buttons with `aria-pressed`, a check mark + fill when pressed
  (never color alone), a colored top border per tone, and counts that
  always cover the whole queue (filtering hides nothing from them; /dq
  additionally caps DRAWN cards at 200 with a loud banner — the
  2026-07-14 live queue held 35,456 issues and drawing them all froze the
  tab).
- **Toasts** (`src/toasts.ts` + `src/components/Toasts.tsx`): one
  persistent `role="log"` aria-live-polite region in the shell; create /
  supersede / certify / resolve confirmations push here. Deterministic
  lifetime: explicit dismiss or route change — never a timer (a
  confirmation that vanishes on its own schedule is a WCAG 2.2.1 trap).
- **Breadcrumbs** (`src/components/Breadcrumbs.tsx`): deep entities carry
  a trail — receipt → lineage (route-level), sampling plan → draw →
  measurements (per worksheet, uniquely-labeled landmarks), safety event →
  correction.
- **Themed nav chrome** (branding v2): the shell applies
  `GET /branding`.chrome (`header_bg`/`header_fg`/`accent`, every pair
  WCAG-refused server-side at write time) as `--chrome-*` custom-property
  overrides in the LIGHT theme only; dark keeps the neutral Headway tokens
  (the served `chrome_note` and the branding page state the per-mode rule).
  Neutral default when unset; charts never read chrome tokens.
- **In-row progress bars** (`src/components/RowProgress.tsx`): the sampling
  plans list shows measured-vs-required per plan — value + label text
  first, bar as the visual echo, with the estimate-ready state visually
  distinct (success fill + "Ready to estimate" tag).

### Today home, motion, tour, teaching empty states (handoff 0021)

- **Skeleton loading states** (`src/components/Skeleton.tsx`): the main
  views (/today, /dashboard, /metrics, /dq, /safety, /sampling,
  /certifications, /metrics/:id/lineage) sketch the shape of the coming
  content instead of a bare "Loading…" line. The blocks are decorative
  (`aria-hidden`); a visually-hidden `role="status"` line carries the
  view's own plain-language loading text. Skeletons never imitate a
  figure — grey blocks only.
- **Motion discipline** (styles.css, the `@media
  (prefers-reduced-motion: no-preference)` block): ALL motion — skeleton
  shimmer, card/toast/dialog enter (150–250ms, CSS-first), interactive-card
  hover lift — lives behind `prefers-reduced-motion`; reduced = INSTANT,
  never slower. Honesty-critical reveals never animate: refusals, load
  errors and FAILED verdicts render as `.alert`/`.banner`/
  `.certificate-failed` with no animation class, and an `:has()` guard
  strips the card-enter animation from any card arriving with an alert
  inside. The tour's scrollIntoView uses `behavior: "auto"` under reduced
  motion.
- **Guided tour** (`src/tour.ts` + `src/components/Tour.tsx`): hand-rolled
  (no tour library), five steps teaching the thesis — /today → a KPI
  receipt opens → the verbatim FTA quote → one lineage step through the
  receipt's own walk door (SPA navigation) → "every number here can prove
  itself". A NON-modal dialog: no backdrop, no focus trap — the page stays
  fully usable (never blocks); focus moves to each step's heading; Escape
  leaves from anywhere; a skip control is on every step. Auto-offers once
  (`headway-tour-seen` in localStorage; finishing or skipping sets it);
  "Take the tour" in the nav restarts it any time. A step whose on-screen
  target does not exist (fresh Headway, no figures) says so honestly after
  the target search gives up — it never fabricates a number to point at.
- **Teaching empty states**: the main views' empty states carry one warm
  sentence + the concrete first action (link or command), role-aware where
  the action belongs to a role. Empty is stated warmly — never urgency,
  never blank.

### Automated checks

Every view test asserts zero axe-core violations (helpers in
`src/test/helpers.tsx`), including with the certify dialog open and the
tour overlay open. A negative control was exercised during development (an
unlabeled input correctly produced a `label` violation), so the gate
demonstrably detects problems.

**Pending (honest gaps):** a manual screen-reader pass (NVDA/VoiceOver) and a
real-browser keyboard walkthrough have not been done in this environment —
they require a live UI against a running API. i18n externalization is started
(all copy lives in `src/copy.ts`) but no i18n framework is wired yet.

## Dependency licenses

Read from the installed packages (`node_modules/*/package.json`):

| Package | License | Runtime bundle? |
|---|---|---|
| react, react-dom 19 | MIT | yes |
| react-router-dom 7 | MIT | yes |
| maplibre-gl 6 | BSD-3-Clause | yes — `/map` chunk only (code-split); whole dependency chain verified permissive by `scripts/license_gate.py --ecosystem node` |
| pmtiles 4 (handoff 0027) | BSD-3-Clause | yes — `/map` chunk only; reads the self-hosted `/basemap/region.pmtiles` archive via same-origin byte ranges |
| protomaps-themes-base 4 (handoff 0027) | BSD-3-Clause | yes — `/map` chunk only; the light/dark street-layer definitions |
| Noto Sans Regular PBF glyphs (vendored, `public/basemap-fonts/`) | SIL OFL 1.1 (© The Noto Project Authors; `OFL.txt` alongside) | yes — static files served same-origin; requested only when basemap labels render |
| react-aria 3, react-aria-components 1 (Adobe) | Apache-2.0 | yes |
| vite 8 | MIT | dev/build only |
| typescript 6 | Apache-2.0 | dev only |
| @vitejs/plugin-react | MIT | dev only |
| vitest 4, jsdom | MIT | dev only |
| @testing-library/react, /user-event, /jest-dom | MIT | dev only |
| oxlint, @types/* | MIT | dev only |
| **axe-core** | **MPL-2.0** | **dev only — never in the shipped artifact** |

Everything that ships in `dist/` is MIT or Apache-2.0 (both OSI-approved
permissive; Apache-2.0 verified from the installed `react-aria` /
`react-aria-components` package.json files — Adobe's React Spectrum stack is
Apache-2.0 throughout, including its `@react-aria`/`@internationalized`
transitive packages). axe-core (the accessibility test engine) is MPL-2.0 —
weak file-level copyleft, used unmodified as a dev-only test dependency; it
is not part of the built artifact. Flagged here for the Platform Architect's
ADR-0001 review rather than silently assumed acceptable.

## Verification status

Refreshed 2026-07-14 (the handoff-0017 UI wave: /compare, /sandbox,
summary-card filters, toasts + breadcrumbs, in-row progress, themed
chrome).

`npm run build` (includes `tsc -b` type-check) — clean:

```
vite v8.1.4 building client environment for production...
✓ 1328 modules transformed.
dist/index.html                   1.22 kB │ gzip:   0.64 kB
dist/assets/index-*.css          30.32 kB │ gzip:   5.47 kB
dist/assets/index-*.js          528.50 kB │ gzip: 151.85 kB
✓ built in 439ms
```

`npm test -- --run` (every view test asserts zero axe violations):

```
 RUN  v4.1.10 ~/headway/web
 Test Files  25 passed (25)
      Tests  145 passed (145)
```

`node scripts/extract-quotes.mjs` — all 12 calcs in the tracker's table
carry verified quotes:

```
extract-quotes: wrote …/web/src/regulatory/quotes.json (dr_pmt_v0: 12, dr_upt_v0: 12, dr_voms_v0: 12, dr_vrh_v0: 12, dr_vrm_v0: 12, pmt_v0: 19, sampling_v0: 19, sscls_v0: 39, upt_v0: 8, voms_v0: 4, vrh_v0: 10, vrm_v0: 10)
```

`npm run check:contrast`: all 71 token pairs (light + dark + chart/series
+ the handoff-0017 summary-card/toast/delta/progress pairs) PASS — "All
token pairs meet WCAG 2.1 AA."

**Live end-to-end (2026-07-14, handoff-0017 wave):** headless-Chrome
click-through against the live Compose API at localhost:8000 (SPA nav only —
in-memory token): login → /compare over real vrh_v0 0.4.0 figures across
two periods (5364.54 vs 5389.40 h; sign-neutral "▲ 24.86 more than the
baseline"; a cell receipt opened live) → /dq summary cards over the real
35,456-issue queue (33 blocking open; the render cap landed from this very
click-through) → /sandbox preview (coverage_threshold 0.95→0.90, real
recompute; VRM refusal-vs-figure rail; nothing persisted) → themed chrome
applied via the audited settings flow, verified light/dark, and reverted.
Evidence in handoff 0017's frontend section. The earlier walking-skeleton
pending (certify a figure live) was closed by the wave-13/15 click-throughs.

---

## "Which trips this affects" — findings in the agency's vocabulary (handoff 0029)

`/dq` renders a finding's `subject_context` as its PRIMARY content: a table
of blocks with trip count, route(s) and the scheduled time span, in the order
their first trip is scheduled to leave. Raw trip identifiers moved into a
collapsed `<details>` disclosure ("Technical detail: trip identifiers") where
they stay copyable for anyone working a ticket.

Nothing is invented and nothing is computed client-side: every label was
resolved once by the calc runner and frozen on the row. Where the feed
carries no block, no route name or no scheduled time, the copy SAYS so
("No block in the schedule feed … Headway shows no block for them rather than
guessing one"). Trips absent from the schedule feed get their own bucket.
Both caps (25 blocks shown, 20 identifiers per block) are stated next to the
true totals.

Graceful degradation is the load-bearing part: a finding with no context —
every one of the 97,067 rows raised before migration 0035 — renders exactly
as it did before, and so does a context whose `version` this UI does not
recognise. Pinned by test.

Finding descriptions now render with `white-space: pre-line`, so the blank
lines the calc writes between paragraphs survive (a live click-through
finding: the paragraphed refusal was rendering as one wall of text). This
improves every finding, old and new.

- `npx vitest run`: **272 passed / 37 files** (+9 in
  `src/test/dqSubject.test.tsx`), including jest-axe on the panel and on the
  opened disclosure.
- `npm run check:contrast`: all 71 token pairs PASS.
- Live axe-core 4.x run IN Chrome against the real `/dq` page (live API, live
  97k queue, the real 2,307-trip finding): **0 violations, 0 incomplete, 223
  colour-contrast nodes checked** — in light AND dark theme.
- Keyboard: Tab reaches the disclosure summary (`:focus-visible` → 3 px solid
  outline, 2 px offset, the house ring), Enter opens it and the identifiers
  become visible. The table is a real `<table>` with `<caption>`, 4
  `<th scope="col">` and 25 `<th scope="row">`.
