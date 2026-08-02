# Handoff: platform → frontend — The control-room shell (composition, not paint)

## Context

Handoffs 0041 and 0043 shipped and are green: the token system (obsidian ground,
one signal-orange identity accent, CVD-safe ok/watch/alert, mono `tabular-nums`),
the data-driven mode selector, two contrast-measured basemap styles, mode-aware
vehicle marks, a flagged-findings layer, `NeedsInvestigation`, and
`RelationshipInspector`. All of it works.

**And the app still looks generic.** Screenshots taken from the running install
on 2026-08-02 were put beside the design studies
(`claude.ai/code/artifact/fe4977ee-…`, and the control-room study before it) and
the gap is obvious to the project lead's eye — correctly.

**The cause is not a regression. Nothing was lost.** It is that 0041 and 0043
each commissioned **tokens and features**, and neither commissioned
**composition**. The agents built precisely what was asked, inside their lanes.
The studies' impact is mostly LAYOUT — a full-bleed map, a persistent dense
rail, a compact command bar, almost no body prose — and layout was never an
output. We shipped the paint and skipped the room.

**The specific findings, measured in the shipped code:**

1. `NeedsInvestigation` renders at `MapView.tsx:1284`, **below** the map canvas
   (`:1190`), in ordinary vertical document flow. In the study it is a
   **persistent rail beside** the map. Same component, entirely different
   effect: in the study it is the first thing you see; today you scroll past a
   full screen of paragraphs and a map to reach it.
2. **20 `<p>` elements in `MapView.tsx`, 22 in `DashboardView.tsx`.** Handoff
   0041 named this exact thing — "the current dashboard's wall of gray
   explanatory paragraphs is the anti-pattern to retire" — but that sentence sat
   in the philosophy section and never reached **Outputs**, so nothing was built
   to it and no gate could catch it. Every figure sits below the fold.
3. **No page-level shell.** The only `display: grid` rules are small internal
   ones (key/value pairs). There is no rail, no hero, no command bar.
4. **The Provenance Terminal does not exist in the app.** It is the most alive
   thing in the study — a live, dense, monospace event stream — and it was never
   commissioned as a component.
5. **The app shell is a two-row wrapping text nav.** It is the most generic
   element on any screen, and no wave has ever owned it.

## Design (binding)

### The rule this wave adds

**Composition is a deliverable, not a consequence of tokens.** A wave that
changes how a page *feels* must state its layout in Outputs, or the layout will
not change. That is the process lesson from 0041/0043 and it is why this wave
exists separately.

### 1. The app shell — a command bar

Replace the wrapping two-row text nav with a **compact command bar**: the brand
mark, the agency name, the current context, and an "as computed" run stamp on
the right. Navigation collapses into a dense, single-row treatment (grouped, or
a menu for the long tail) — the nav currently spends two full rows of vertical
space on 17 links before any content appears. Keyboard access and focus order
must not regress; this is chrome, and chrome is where accessibility is easiest
to lose.

### 2. The map page — full-bleed hero + persistent rail

The map becomes the **hero**: the canvas fills the viewport beside a persistent
right rail, rather than sitting below a screen of prose. The rail carries, in
this order:

1. **Needs investigation** — the existing `NeedsInvestigation` component, moved,
   not rebuilt. It stays the accessible entry point to the canvas.
2. **Fleet readout** — the figure cards, monospace and flat.
3. **Provenance terminal** — new (see 4).

Controls (window, street style, mode highlight) move into a compact control
strip in the map chrome. `RelationshipInspector` keeps its slide-over behaviour.

### 3. The dashboard — figures above the fold

Same paradigm: the readout cards are the first thing on the page. Lens and mode
controls become a compact strip, not three stacked paragraph-wrapped blocks.

### 4. The Provenance Terminal (new component)

A live, dense, monospace stream of what the platform is doing — figures
computed, leaves verified, findings raised, boardings held, refusals issued —
with a severity rail per row and a LIVE indicator. It is the study's most alive
element and the clearest possible expression of "this system is working and
showing you its work."

**Honesty rules for it, non-negotiable:** every row is a real event from a real
endpoint — never a synthesised or decorative tick. If there is nothing to show,
it says so; it does not invent activity to look busy. It never implies a figure
is good or bad, only what happened. It respects `prefers-reduced-motion` (no
slide-in; the stream still updates).

### 5. The prose: RELOCATE, never delete

**This is the delicate part and the easiest thing to get wrong.** Those
paragraphs are not decoration — they are the plain-language honesty this project
is built on, written for a reader with zero SQL and one week of Linux. Deleting
them to win a screenshot would trade the product's soul for a nicer picture.

The rule is **progressive disclosure**:

- Every honesty statement keeps a **one-line summary always visible** (e.g.
  "Positions observed, never interpolated" under the map; "Figure scope: agency"
  under the selector).
- The full explanation moves into an expandable "What this shows" / "How this
  works" disclosure, closed by default, **and is not shortened** when it moves.
- **Nothing that states a limitation, a refusal, or a caveat may be hidden
  behind a disclosure** — a refusal, a held count, a staleness warning, or a
  "not an NTD figure" badge stays visible at all times. Explanation collapses;
  admission never does.

A test should pin that last rule: assert the refusal/held/simulated strings are
present without expanding anything.

## Outputs

The command bar; the map hero + persistent rail (moving `NeedsInvestigation`,
not rebuilding it); the dashboard figures-first composition; the Provenance
Terminal component wired to real events; the prose relocated under the
disclosure rules above. AA verified in both themes; `prefers-reduced-motion`
honored; keyboard order and focus visibility verified through the new shell; web
tests green (411 at time of writing) with new tests for the disclosure rule and
the terminal's empty state; **before/after screenshots at 1440×960 for the map
and the dashboard**, captured with `tools/screenshots/capture.mjs`.

Sequence: shell first (it frames everything), then the map hero + rail, then the
dashboard, then the terminal.

## Open Questions

- **Does the rail persist across pages, or is it map-specific?** (Recommended:
  map-specific for this wave — a global rail is a bigger commitment and the map
  is where it earns its keep.)
- **Where does the long nav tail go** — grouped menus, or a command palette?
  A palette is more modern but adds a discovery problem for an audience that is
  one week into Linux; grouped menus are duller and safer.
- **What feeds the Provenance Terminal?** Existing endpoints polled (cheap,
  honest, slightly laggy) or a new server-sent stream (livelier, a new
  surface to secure and rate-limit)? Recommended: poll existing endpoints in v0
  and label the cadence, rather than build a streaming surface before the
  composition is proven.

---

## Verification Evidence (frontend — wave E)

### The open questions, answered

1. **Does the rail persist across pages?** No — **map-specific**, as
   recommended. A global rail is a bigger commitment and the map is where it
   earns its keep.
2. **Where does the long nav tail go?** **Grouped menus**, not a palette. A
   palette hides the map of the product behind a keystroke, and this audience
   is one week into Linux. Each group is a *disclosure over ordinary links*
   (`web/src/components/NavGroup.tsx`) — a real `<button aria-expanded
   aria-controls>` over a `<ul hidden>`, so every destination stays a link
   with the same keyboard contract the rest of the nav has, Escape closes and
   returns focus to its trigger, and a closed group's links are genuinely out
   of the tab order rather than merely invisible.
3. **What feeds the terminal?** **Polling, labelled**, as recommended. No new
   server surface.

### What shipped

**1. The command bar** (`web/src/components/Layout.tsx`,
`web/src/components/RunStamp.tsx`, `web/src/components/NavGroup.tsx`). Two
dense rows replace the wrapping two-row nav:

- Row 1 — brand rule + the agency's own name, the room you are in, an **"as
  computed" run stamp read from the real calculation-run record**
  (`GET /calc-runs`, newest first), then the utility cluster. The stamp is a
  stamp, never a figure: it prints the server's `finished_at` verbatim with
  the run's status, says `no calculation run on record` when there is none,
  `a calculation run is in progress` while one is open, and `run record
  unavailable` when the read fails. It never shows a comforting blank.
- Row 2 — **one** navigation row: Today · Live map · Dashboard · Metrics ·
  Data quality · **Reports ▾** · **Records ▾** · **Tools ▾** · Certify ·
  Admin · Public data. Measured in a real browser at 1440×960: the whole
  shell is now **~92 px** (a command bar of ~46 px over a nav row of ~46 px),
  against a two-row wrapping nav before.

**2. The map — full-bleed hero + persistent rail** (`web/src/views/MapView.tsx`).
`<main>` drops its reading-width column on `/map` (`main.page-full`) and the
page composes its own grid: `.map-shell` is `minmax(0,1fr) 23rem` with a 1 px
etch gap and `height: calc(100vh - 7rem)`. The rail carries, in order:

1. the server's own notices (staleness, caps, geometry notes) — at the *top*,
   because an admission you have to scroll to is an admission that did not
   happen;
2. **`NeedsInvestigation`, MOVED, not rebuilt** — same component, same props,
   same accessible entry point to every flag; it takes the rail's slack and
   scrolls in place so the sections under it stay on screen;
3. the **fleet readout** — mono/`tabular-nums` cards over counts the *server*
   stated (`vehicle_count`, the DQ page's whole-queue `total`, the modes the
   schedule join produced). The card that needs a person carries the alert
   rail **on its frame**; no figure carries a glow or a status colour;
4. the **provenance terminal**.

Controls collapsed into one compact strip in the map chrome (window · street
style · mode highlight · staleness chip · refresh · last-checked).
`RelationshipInspector` keeps its slide-over behaviour, untouched.

**3. The dashboard — figures above the fold** (`web/src/views/DashboardView.tsx`,
`web/src/components/ModeBar.tsx`). One `.control-strip` replaces three stacked
paragraph-wrapped blocks. Measured at 1440×960: the first certified figure now
paints at **y ≈ 680 px**, inside the first screen.

**4. The Provenance Terminal** (`web/src/components/ProvenanceTerminal.tsx`).

- **What it polls, and how often:** `GET /calc-runs` (8 newest runs; the 3
  newest also contribute one row per figure outcome from the runner's own
  summary) and `GET /dq/issues` (12 newest findings), **every 30 s**. Both
  endpoints already existed and are already authorized — no new surface to
  secure or rate-limit. The cadence is printed on the panel
  (`copy.terminal.cadence`), as is the row cap (12) and what the panel reads.
- **Honesty:** every row is built from a record the API served and carries
  **that record's own timestamp** — there is no synthesised tick anywhere in
  the component. With nothing on record it prints the empty state rather than
  inventing activity. A failed read says so *instead of* the empty state:
  silence and "we could not look" are different sentences.
- **It never grades a figure.** A computed figure takes the neutral rail;
  the CVD-safe `watch`/`alert` set appears only where the *platform* assigned
  a severity (a finding), and the non-semantic identity accent marks
  Headway's own refusals — declining to emit is the product working, neither
  good news nor bad. The tag word (`COMPUTED` / `REFUSED` / `RAISED` /
  `FAILED` / `STALE`) carries the meaning; the rail only echoes it.
- **Reduced motion:** the slide-in and the LIVE blink are the only motion,
  and both live inside the single `@media (prefers-reduced-motion:
  no-preference)` block the design suite pins. The poll and the rows are
  outside it — reduced motion stops the decoration, never the stream.
- **Known v0 limitation:** a long row is visually truncated with an ellipsis
  (the stream is one line per event, by design). The full text is in the DOM
  for a screen reader, and the same events are fully readable in the
  worklist and the data-quality queue.

**5. The prose: RELOCATED, never deleted.** `web/src/components/Disclosure.tsx`
is the only mechanism, and it is only ever wrapped around explanation. The
rule applied, written down so a later wave can apply the same test:

> An **explanation** may fold — how a control behaves, what a page is for,
> what a chart is showing. It is carried across **verbatim**; nothing was
> shortened when it moved.
> An **admission** never folds: a refusal, a held/excluded/capped count, a
> staleness or gap warning, a scope receipt, a simulated badge, or a "this is
> not narrowed / not a total this page added up / not an NTD reported figure"
> boundary.

| String | Where it went |
| --- | --- |
| `map.intro`, `map.window.note`, `map.basemap.style.note`, `map.modeFilter.note` | folded into "How these controls work" in the map toolbar, verbatim |
| `dashboard.intro` | folded into "What this shows" under the `h1`, verbatim |
| `dashboard.mode.intro`, `dashboard.lens.intro`, `dashboard.lens.presetHints` | folded into "How this works" inside their own control, verbatim |
| `map.summary` (new), `dashboard.summary` (new) | the always-visible one-liners that replace them on screen |
| `map.pollNote`, `map.chip.*`, `res.note`, `truncatedIntro`, geometry/basemap legend notes, ODbL credit, `ops_note` + `OpsBadge`, `findings.legendNote`, `mode.scopeReceipt`, `mode.agencyNote`, `mode.dataDrivenNote`, `mode.dqNote`, `mode.opsNote`, `lens.groupingNote`, `dq.wholeQueueNote`, `dq.blockingFlag`, `AsReportedNote`, `refusalLines`, `SimulatedBadge` | **untouched and always visible** |

**Proof the carve-out holds:** `web/src/test/disclosure.test.tsx` asserts each
of those admissions is `toBeVisible()` on `/dashboard` and `/map` **with every
disclosure still closed** (it first asserts every `aria-expanded` is `false`),
and asserts the moved explanations are present but `not.toBeVisible()` —
i.e. still in the document, unshortened, merely folded. Opening the control
reveals exactly the original string.

### Commands run, at this commit

```
cd web
npx tsc -b                 # clean
npm run build              # clean
npm test (vitest run)      # 46 files, 423 passed, 0 failed, 0 skipped
npm run check:contrast     # "All token pairs meet WCAG 2.1 AA."
npm run check:map-contrast # 27 passed
npm run lint               # 4 pre-existing fast-refresh warnings, 0 errors
```

411 → **423** tests: +12 new (4 disclosure carve-out, 3 terminal, 5 command
bar). Four existing tests were updated, none weakened:

- `certifications.test.tsx` — the Certifications link is now one disclosure
  deep; the test asserts it is *absent* while the group is closed, opens
  "Records", then asserts the same `href`. That is a stronger assertion than
  before.
- `certify.test.tsx`, `public.test.tsx` — the shell now makes one extra
  round-trip on mount (the run stamp), so these locate their call by **path**
  instead of by position.
- `map.test.tsx` — the terminal also reads `/dq/issues`, so the flag-layer
  assertion identifies its request by its own `severity=blocking` filter
  rather than by being the first call to that path.

**Suite determinism:** the suite was intermittently failing one random test
per run under full parallelism (a different test each time, all green in
isolation) once the shell gained its extra mount-time round-trip.
`vite.config.ts` now caps the worker pool at 4 and `src/test/setup.ts` widens
the Testing Library `findBy*` window to 4 s. Neither weakens an assertion;
three consecutive full runs are green.

### AA verification (contrast math, not vibes)

Every colour pair this wave introduces is an **already-registered, measured
pair** in `web/scripts/check-contrast.mjs` — no new unmeasured pair was
created:

| Use | Light | Dark |
| --- | --- | --- |
| readout figure, terminal message, hero caption (text on card) | 15.80:1 | 15.95:1 |
| context slot, run stamp, receipts, terminal time/notes (muted on card) | 6.39:1 | 7.28:1 |
| map toolbar labels (muted on page plane/surface) | 6.00:1 | 7.80:1 |
| disclosure toggle (accent on card / on surface) | 6.39:1 / 6.00:1 | 7.13:1 / 7.64:1 |
| terminal `REFUSED` tag + rail, brand rule (identity signal) | 6.01:1 | 7.13:1 |
| terminal LIVE indicator (status ok) | 7.30:1 | 8.73:1 |
| terminal `RAISED` warning tag + rail (status watch) | 5.19:1 | 12.90:1 |
| terminal alert tag + the readout card's attention rail (status alert) | 7.93:1 | 5.46:1 |

The rails and the LIVE dot are non-text marks over 3:1 in both themes, and
none of them is the sole carrier of meaning — every one is paired with a word.

### Keyboard and focus

- Tab order verified by test: skip link → tour → theme → sign out → the nav
  row in visual order → `<main>`. Focus management on route change is
  unchanged.
- A nav group's links are `hidden` when closed (out of the tab order and out
  of the accessibility tree); Escape closes the group and returns focus to
  its trigger; a pointer press outside closes it without stealing focus.
- A live-browser bug was found and fixed during this wave: a component
  `display` rule was overriding the `hidden` attribute, so closed nav panels
  were painting (and would have stayed focusable). `styles.css` now carries a
  global `[hidden] { display: none !important; }`.
- axe (jest-axe) is green on every changed surface, including `/map` with the
  rail and the terminal mounted.

### Screenshots — PARTIAL, and here is exactly what is missing

- **Before:** `docs/images/map.png` and `docs/images/dashboard.png`, captured
  from the real running install on 2026-08-02 (commit `ca3c801`). Those are
  the very screenshots whose comparison with the studies produced this
  handoff, so they are the honest "before".
- **After (real install): NOT CAPTURED — blocked.** `tools/screenshots/capture.mjs`
  must sign in, and the installation's admin password is set interactively and
  stored nowhere this session can read. Resetting it
  (`install.sh --reset-admin-password`) would change a credential the operator
  holds, which is not a change to make unasked.

  One paste, once `SHOT_USER`/`SHOT_PASS` are known (the nav link texts
  "Dashboard" and "Live map" are unchanged, so the existing plan still works):

  ```sh
  google-chrome --headless=new --remote-debugging-port=9333 --no-sandbox \
    --disable-gpu --hide-scrollbars --user-data-dir=/tmp/hw-shot about:blank &
  mkdir -p /tmp/hw-shot-driver && cd /tmp/hw-shot-driver && npm init -y && npm i ws@8
  SHOT_BASE=http://127.0.0.1:8080 SHOT_USER=<user> SHOT_PASS=<password> \
  SHOT_OUT=<repo>/docs/images SHOT_DARK=1 \
  SHOT_PLAN='[{"nav":"Dashboard","file":"dashboard.png","wait":4500},{"nav":"Live map","file":"map.png","wait":5000}]' \
  node <repo>/tools/screenshots/capture.mjs
  ```

- **What WAS verified in a real browser:** the composition was driven end to
  end in headless Chrome at 1440×960 (deviceScaleFactor 2) against the real
  built bundle served over a **local layout stub with FICTIONAL data**, which
  is how the header-wrap, the shell-height and the `[hidden]` bugs above were
  found. Those captures are committed **only** as
  `docs/images/handoff-0044/LAYOUT-PREVIEW-FICTIONAL-DATA-*.png`. They are
  named that way on purpose: they show real UI code over invented numbers and
  **must never be used as product evidence** (see
  `tools/screenshots/README.md`).

### Deferred

- The real-install after-screenshots (above).
- A server-sent event stream for the terminal — deliberately not built; v0
  polls and says so, per this handoff's own recommendation.
- The terminal's one-line rows truncate visually at narrow rail widths.
- The rail is map-specific; making it global is a separate decision.
- `docs/images/map.png` / `dashboard.png` in the README still show the
  pre-0044 composition until the capture above is run.

### Lane discipline (wave F ran concurrently)

Touched: `web/src/components/{Layout,NavGroup,RunStamp,ProvenanceTerminal,Disclosure,ModeBar}.tsx`,
`web/src/views/{MapView,DashboardView}.tsx`, `web/src/styles.css`,
`web/src/copy.ts` (new `shell` / `disclosure` / `terminal` blocks plus the
`map` and `dashboard` blocks), `web/vite.config.ts`, `web/src/test/**`,
`docs/images/handoff-0044/`.

**Not touched:** `web/src/views/AdminView.tsx`, `services/api/**`,
`db/migrations/**`, and no `admin`/`sso` block in `copy.ts`. No lane crossing
was needed.
