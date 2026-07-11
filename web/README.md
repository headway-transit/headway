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
`scripts/extract-quotes.mjs` copies the VERBATIM FTA NTD Policy Manual quotes
from `services/calc/REGULATORY_TRACKER.md`'s "Verified definitions" sections
into a static, versioned JSON keyed by `calc_name`. Quotes are never
paraphrased or generated; the script fails loudly (non-zero exit) if any calc
in the tracker table lacks quotes, and `src/test/quotes.test.ts` fails the
suite if any calc named in the fixtures lacks quotes. Regenerate after the
NTD/Compliance Engineer updates the tracker; never hand-edit the JSON.

### API base URL

Set `VITE_API_BASE_URL` to the API origin (no trailing slash), e.g.:

```sh
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

Unset, requests go to the same origin (for co-hosting or a dev proxy).

### Sessions

The bearer token from `POST /auth/login` is held **in memory only** (module
state, `src/auth/session.ts`): nothing is written to localStorage, and a page
reload signs you out. The hardening increment is a server-set `httpOnly`,
`Secure`, `SameSite` cookie session, which removes the token from JS reach
entirely. Any 401 clears the session and returns you to `/login`.

## Views

| Route | What it does |
|---|---|
| `/login` | Local-account sign-in (ADR-0011). Failures announced via `role="alert"`, verbatim. |
| `/metrics` | Computed values table: metric, unit, period, value (verbatim string), calculation name+version, certification status. Calc versions below 1.0.0 carry a "Pre-verification" tag and a plain-language banner (they are marked PRE-VERIFICATION in `services/calc/REGULATORY_TRACKER.md` — not certifiable figures yet). EVERY figure's "Details" opens its **Receipt** (`src/components/Receipt.tsx`): story line, coverage meter + exclusions, the verbatim FTA rule + citation, flags, and the walk to raw records. Certifying officials get labeled row checkboxes and the "Certify selected figures" action. |
| `/metrics/:id/lineage` | "How this number was made": the provenance tree from `GET /metrics/values/{id}/lineage`. Default is the **lineage graph** (`src/components/LineageGraph.tsx`) — a hand-rolled accessible SVG flow (figure → processing steps → raw records; raw tier collapsed to a count node, expanding 20 at a time; arrow keys move within/between tiers, Enter toggles). A "Text view" toggle is always visible and renders the FULL nested-list tree (every node, complete record ids) — the graph is progressive enhancement, never the only path. |
| `/reports/monthly` | Monthly ridership preview: VRM/VRH/UPT for a picked month, verbatim, with certification status, coverage summary, per-row Receipt, provenance links, simulated-data banner, and CSV export of the exact served strings. |
| `/dq` | Data-quality queue: severity as text + icon + color (never color alone), status/owner/description, blocking issues prominent with their consequence stated. Resolve action (required resolution note) appears for data stewards and above. |

The certify flow: select figures → "Certify selected figures" → a
focus-trapped `aria-modal` dialog that lists **exactly** which figures (value,
period, calculation + version, each with its provenance link) are being
attested → required attestation statement → `POST /certifications`. The API
is the system of record: success shows the certification id the API returned,
and the table is re-read from the API rather than assumed.

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

### Keyboard map

- `Tab` — every interactive element is reachable in DOM order with a visible
  focus ring (`:focus-visible`, 3px accent outline).
- First `Tab` on any page — "Skip to main content" link.
- Route change — focus moves to `<main>` so the new page is announced.
- Metrics: `Space` toggles a row checkbox; `Enter` on "Certify selected
  figures" opens the dialog.
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

### Automated checks

Every view test asserts zero axe-core violations (helpers in
`src/test/helpers.tsx`), including with the certify dialog open. A negative
control was exercised during development (an unlabeled input correctly
produced a `label` violation), so the gate demonstrably detects problems.

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

`npm run build` (includes `tsc -b` type-check) — clean:

```
vite v8.1.4 building client environment for production...
✓ 1300 modules transformed.
dist/index.html                   0.45 kB │ gzip:   0.29 kB
dist/assets/index-Dh6dwN31.css    8.32 kB │ gzip:   2.12 kB
dist/assets/index-DPNF6eeu.js   320.09 kB │ gzip: 101.33 kB
✓ built in 200ms
```

`npm test -- --run`:

```
 RUN  v4.1.10 /home/daniel/headway/web
 Test Files  9 passed (9)
      Tests  47 passed (47)
```

`node scripts/extract-quotes.mjs`:

```
extract-quotes: wrote …/web/src/regulatory/quotes.json (upt_v0: 8, vrh_v0: 10, vrm_v0: 10)
```

`npm run check:contrast`: all 19 token pairs PASS (see table above).

**PENDING — live end-to-end against a running API.** Docker is unavailable in
this environment, so the UI has only been exercised against the exported
OpenAPI contract with mocked fetch. Before this increment is Done per the
role's Definition of Done: run the stack, sign in with a seeded
certifying-official account, certify a seeded VRM figure, walk its lineage to
a raw record, and resolve a DQ issue — then capture that evidence here.
