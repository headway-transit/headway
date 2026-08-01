# Handoff: platform → frontend — Dashboard mode views + a design-forward UI pass

## Context

The dashboard is hardcoded to the agency-wide rollup (`scope = "agency"`); there is
no way to view figures **by mode** (Fixed route, Dial-A-Ride, Via, Rideshare/vanpool,
…). The partner agency's ITS manager asked for it directly ("where is the Rideshare
view?").

**The data dimension already exists.** The calc engine computes and persists
per-mode figures on the `--per-mode` path (handoff 0009): `scope = "mode:bus"` for
fixed route, `mode:DR` / `mode:DR:tos:<tos>` for demand response, alongside the
`agency` rollup — and the metrics API already returns those scoped rows. So mode
views are a **frontend wave**, not a backend build; the dashboard simply filters
`agency` today.

**Two gates, kept honest:** (1) the UI has no mode selector — this wave; (2) some
modes have no figures *yet* — Rideshare/vanpool is gated on the FTA vanpool-rules
calc wave (Samsara data now landing, zero figures by design), Via's adapter isn't
built, and "Arc" has no data source. A mode with no figures shows a real,
inviting empty state — never a fabricated zero.

**And a standing design directive (Daniel, 2026-07-31):** apply *modern, visually
appealing, genuinely-enjoyable-to-use* design to a domain (NTD compliance) where
software is usually boring and unpleasant. This wave is the first place to prove it.

## Design (binding)

### The mode selector
1. A **"Mode" selector alongside the existing "Audience lens" and "Group trends by"
   controls** — same paradigm, one honest place, nothing hidden behind a fly-out or
   a separate sub-menu (both rejected: fly-outs hide state; a sub-menu splits nav).
   A dropdown once the count exceeds ~5 modes; a segmented control below that.
2. **Data-driven, never hardcoded.** The selector lists the modes that actually have
   figures (the distinct `mode:*` scopes present), plus "All modes (agency)" as the
   default. Rideshare/Via/Arc appear automatically the day their calc waves land — a
   hardcoded list that shows an always-empty mode would be a lie.
3. **Re-scope, never derive.** Selecting a mode filters every figure and trend to
   that mode's persisted rows, verbatim with its `metric_value_id` receipt — it never
   sums, averages, or synthesizes a per-mode number (the page's own "charts scale the
   picture, never the figures" promise, upheld).
4. **Inviting per-mode empty states.** A mode with no figures yet says so warmly and
   points at why ("Vanpool figures appear once the FTA vanpool rules are in place")
   — designed, not a flat blank.

### The design philosophy this wave establishes (applies to all UI work)

**North star (the success test):** an auditor opens Headway for the first time and
their jaw drops — not at flash, but because it has *all* the data, it is genuinely
easy to use, it is beautiful, and it makes the most tedious part of their job —
tracing a reported figure back to the source records that defend it — something they
actually *enjoy*. An auditor's dread is the hunt through spreadsheets and PDFs to
prove a number; Headway turns that hunt into the beautiful, instant, interactive
centerpiece. Every design decision below serves that moment. (This is a jaw-drop only
Headway can deliver: plenty of dashboards are pretty, but a pretty dashboard that can
*show its work* — click any figure to its lineage, raw records, quoted FTA
definition, and the human justification notes — is the moat. The receipts we've been
building all along ARE the wow; this wave is their presentation layer.)

The aspiration is **jaw-dropping** — the standard is the Hugging Face incident-replay
dashboard the project lead set as the target, already distilled in
`docs/design/toc-replay-dashboard.md`. Modern, immersive, genuinely enjoyable to
use. The non-negotiables are not a ceiling on that ambition — they are woven into it.

- **Aim high on visual ambition, not toward restraint.** The reference is HF's
  incident-replay experience: cinematic, temporal, alive — a boring domain made
  something people *want* to open. Lean *into* the `frontend_aesthetics` guidance
  (distinctive type, a committed palette with sharp accents, depth and atmosphere,
  purposeful motion), not away from it. The current dashboard's wall of gray
  explanatory paragraphs is the anti-pattern to retire.
- **Honesty is the signature feature, not the dampener.** The TOC blueprint's core
  move — *reconstruction is not observation*; observed data and inferred motion look
  visibly different; gaps break a trail rather than bridge it — is the model: the most
  striking thing on the screen is *also* the most honest thing. Headway's rigor
  (verbatim figures, "charts scale the picture, never the figures," AA-verified
  tokens, the CVD-safe validated palette, `prefers-reduced-motion`) becomes part of a
  distinctive visual language, not a list of things the design can't do. A number
  never animates in a way that misleads; no gamification implies a figure is "good" —
  and *that discipline reads as craft*, the way the HF dashboard's precision does.
- **What the HF reference concretely gives us** (viewed 2026-07-31,
  huggingface-anatomy-of-frontier-lab-model-intrusion.static.hf.space): a
  **forensic-authoritative** character — a dark, control-room surface; **monospace
  for the precise things** (timestamps, counts, ids) so precision *reads*; a
  committed palette with clinical accents (active/threat vs. completed/quiet) rather
  than a cheery even spread; **coordinated multi-panel** views that update together;
  **progressive reveals** (nodes "ignite" only as reached — nothing is shown before
  it's earned); and precision-as-craft ("~17,600 logged actions," "as observed").
  That last one is the point: **its premium feel comes from rigor, which is exactly
  Headway's honesty ethos** — so we are not dressing up the numbers, we are letting
  the discipline that makes them trustworthy also make them beautiful.
- **Scope note:** the full *temporal replay scrubber* is the signature of the
  separate TOC replay dashboard (`docs/design/toc-replay-dashboard.md`, blocked on the
  retention decision) — do not force a scrubber onto the metrics dashboard. This wave
  inherits the HF *aesthetic and polish* — control-room surface, monospace precision,
  coordinated panels, an orchestrated page-load and a genuinely satisfying lens/mode
  switch (staggered reveals, smooth trend transitions that yield to reduced-motion),
  empty/loading states that feel *designed*. A high-fidelity `/design-sync` pass
  against the HF target should drive the treatment, not incremental tweaks.

## Outputs

The mode selector (data-driven, re-scope-only) + per-mode empty states + the
design-forward pass on the dashboard surfaces this touches; AA + palette + reduced-
motion verified; web tests; screenshots (light + dark). Sequence: ship the selector
against the modes that have data (Fixed route, Dial-A-Ride) first; the rest light up
as their calc waves land. Consider a high-fidelity `/design-sync` pass (the
claude.ai/design project, `docs/design/claude-design-prompt.md`) to drive the visual
treatment rather than incremental tweaks.

## Open Questions

- **What is "Arc"?** — the agency named it as a mode; it needs a data source before
  it can appear, and we need to know what service it is.
- Should the Mode selector and Audience lens compose freely (e.g. "Operations lens ×
  Dial-A-Ride"), or are some combinations meaningless and hidden?
- Does the `frontend_aesthetics` north star get a formal "compliance calibration"
  note (credible-not-flashy) committed into `docs/design/claude-design-prompt.md`, so
  it governs future design-sync runs? (Recommended — this wave is the test case.)

---

## Verification Evidence — frontend (2026-08-01)

Built in the frontend worktree, Track A of two concurrent tracks (Track B held
handoff 0043, the map basemap styles). Nothing outside the frontend lane was
touched — no map view, no basemap doc, no backend, no `docs/basemap.md`.

### 1. What shipped

**A. The data-driven mode selector** (`web/src/reports/modes.ts`,
`web/src/components/ModeBar.tsx`, wired in `web/src/views/DashboardView.tsx`).

- **Data-driven, never hardcoded.** `modeOptions(rows)` returns the distinct
  `mode:*` scopes actually present in what `GET /metrics/values` served, plus
  "All modes (agency)" as the default. **No mode name appears anywhere in the
  frontend as an option.** Rideshare/Via/Arc — and any mode nobody has thought
  of — appear the day their calc wave persists a `mode:*` row, with no frontend
  change. A test asserts that a payload with only `agency` rows offers *zero*
  modes, which is exactly what a hardcoded catalogue would have got wrong.
- **Re-scope, never derive.** `rowInScope()` is exact-string selection.
  Selecting a mode filters the hero tiles, the UPT chart, the VRM/VRH small
  multiples, the coverage chart, every table view and the trend sparklines to
  that mode's persisted rows — served verbatim, each still one click from its
  own `metric_value_id` receipt (`/metrics/{id}/lineage`). Nothing sums,
  averages or differences the modes. A test asserts that the sum
  (11111.10 + 8888.80 = 19999.90) and the difference (2222.30) of the agency and
  mode figures appear **nowhere on the page, in any formatting**.
  A DR type-of-service scope (`mode:DR:tos:DO`) is its own option and never
  folds into `mode:DR` — folding would need arithmetic nobody performed.
- **The scope receipt.** The persisted scope string is rendered verbatim in
  monospace under the selector *and on every stat tile* (the tile shows the
  **row's own** scope). What you picked and what the rows were filtered on are
  the same string, on screen. The tiles' heading also names the mode
  ("Latest certified figures — Bus"), so a mode slice can never be misread as
  the agency rollup.
- **Shape follows count.** A segmented `aria-pressed` group (the existing
  filter-bar pattern) up to `MODE_SEGMENT_MAX = 5` modes; above that a
  react-aria-components `Select` listbox, so keyboard and screen-reader
  semantics come from the library rather than hand-rolled ARIA. Both forms are
  covered by tests, including the keyboard path through the dropdown.
- **Inviting per-mode empty states.** A mode with nothing computed in the
  selected dates gets a designed panel — mono scope eyebrow, its name, why it
  is empty ("Headway would rather show you an empty page than a number nobody
  computed"), how to widen the range, and the *Compute figures* door for roles
  that may run one. **No fabricated zero anywhere**; the charts are absent
  rather than flatlined at 0. Per-card empty lines also name the mode.
- **Surfaces with no mode dimension say so.** Operations metrics are computed
  **per route**, and data-quality tallies count **issues, not figures**. Under a
  mode both keep showing what they actually have *and state in words that they
  are not narrowed* — instead of letting agency numbers sit silently under a
  mode heading. **Fail-loudly fix found while building:** an early version
  replaced the whole chart grid with the per-mode empty panel, which hid the
  data-quality card — an open **blocking** issue would have vanished by
  selecting an empty mode. The DQ card is now rendered unconditionally, and a
  test pins it.
- **Server-side re-scope too.** The trend request carries `scope=mode:<x>` when
  a mode is selected (the agency default sends no scope param, so existing
  behaviour is byte-identical), and the returned points are also filtered
  client-side by exact scope.

**B. The design-forward token pass** (`web/src/styles.css` — sole-owner file).

Direction as settled: *Vignelli transit-diagram × avionics data-density,
executed FLAT.*

- **Obsidian ground (dark).** Card surface → graphite `#0f131b`, page plane →
  void `#07090e`, plus a real raised step `#1a2130`. Panel separation is a **1px
  hairline etch** (`--color-border: #242c3a`). `--shadow-1` is now `none` in
  **both** themes and `--radius-*` dropped to 3–4px — no bevels, no faux-3D, no
  elevation stack. Only genuinely-floating layers (tooltip, toast, the mode
  popover) keep `--shadow-2`.
- **One identity accent: signal-orange, non-semantic.** Used for the wordmark
  rule, active controls, the sparkline, section eyebrows and the empty-state
  rail — never to encode state. In the dark theme it *is* `--color-accent`
  (the dark accent has always been pinned by us, because the server's brand
  guardrail certifies light surfaces only), so dark mode reads obsidian +
  orange throughout.
- **Semantic status kept separate and unified.** `--status-ok / --status-watch /
  --status-alert` are new tokens, and the dark `--chart-status-*` severity marks
  were re-pointed at the same values so the palette carries no second amber and
  no second red. No new signal hues were added.
- **Typography.** `--font-display` for headings and eyebrows;
  **`--font-mono` + `tabular-nums` for every figure, id, timestamp and receipt**
  (the stat tiles' big figures moved from proportional to mono — a test pins
  it). "No certified figure yet" is deliberately *not* dressed as a figure, so
  an absence never reads as a reading.
- **Honest attention-glow.** `.attn` puts a halo on the card **frame**
  (a 3px edge-rail with a soft bloom), never behind a figure. It is scarce: the
  only user today is the data-quality card, and only while a **blocking** issue
  is open — the one thing on the page that genuinely needs a person. Every
  flagged card also carries a **shape** (the severity octagon) and a
  **sentence**, so the signal survives for a reader who perceives no glow at
  all. There is **no all-clear glow**: a clear queue gets nothing. The pulse
  lives inside `@media (prefers-reduced-motion: no-preference)`, so reduced
  motion leaves a static rail — never a slower one.
- **Figures never mislead.** No count-up animation was added; figures are still
  the API's strings rendered once, flat. Charts still scale the picture only.

### 2. Test + build evidence

Run in `web/` at the worktree HEAD of this branch:

```
$ npx tsc -b                # clean
$ npx vitest run
  Test Files  40 passed (40)
       Tests  307 passed (307)
$ npm run build             # ✓ built in 616ms, tsc -b + vite build clean
$ npm run check:contrast    # All token pairs meet WCAG 2.1 AA.
$ npx oxlint                # exit 0
```

The suite went **289 → 307** (+18). No test was deleted, skipped or weakened;
the 289 pre-existing tests all still pass unchanged. New files:

- `web/src/test/modes.test.tsx` (11) — the mode vocabulary unit tests plus the
  dashboard behaviours above (data-driven options, verbatim re-scoping with
  receipts, the no-derived-figure assertion, the per-mode empty state, the
  not-narrowed notices, the server re-scope, the dropdown keyboard path).
- `web/src/test/design.test.tsx` (7) — the visual honesty rules as assertions:
  all motion inside `prefers-reduced-motion`, no glow behind any figure
  (`text-shadow` appears nowhere; no `box-shadow`/`filter` in any `.figure` or
  `.stat-value` rule), `--shadow-1: none` in both themes, exactly one identity
  accent that is none of the six status values, mono tabular-nums on figures,
  and the DOM-level attention rules (frame-only flag, shape + sentence, no
  all-clear glow).

`jest-axe`-equivalent (`axe-core`) assertions run in the new mode and design
tests, including with the dropdown popover open.

### 3. AA contrast — verified by arithmetic, not by eye

`npm run check:contrast` (`web/scripts/check-contrast.mjs`) is the SC 1.4.3 /
1.4.11 gate, because jsdom cannot compute contrast. Every dark pair was
recomputed against the new obsidian ground and every new token registered.
Selected values (full output from the script):

**Light theme (surfaces `#ffffff` card / `#f6f8fa` plane — deliberately
unchanged, see §5):**

| Pair | Ratio | Min |
| --- | --- | --- |
| identity signal `#a84400` on `#ffffff` | **6.01:1** | 4.5 |
| identity signal `#a84400` on `#f6f8fa` | **5.65:1** | 4.5 |
| label `#ffffff` on identity fill `#a84400` | **6.01:1** | 4.5 |
| identity sparkline/rule on card (non-text) | **6.01:1** | 3.0 |
| status ok `#1c632f` on `#ffffff` | **7.30:1** | 4.5 |
| status watch `#946300` on `#ffffff` | **5.19:1** | 4.5 |
| status alert `#9f1b1b` on `#ffffff` | **7.93:1** | 4.5 |
| status alert edge-rail (non-text) | **7.93:1** | 3.0 |

**Dark theme (card `#0f131b`, plane `#07090e`, raised well `#1a2130`):**

| Pair | Ratio | Min |
| --- | --- | --- |
| body text `#e9eef5` on card / plane / well | **15.95 / 17.08 / 13.81:1** | 4.5 |
| muted text `#96a3b7` on card / plane | **7.28 / 7.80:1** | 4.5 |
| identity + link `#ff7a1a` on card / plane | **7.13 / 7.64:1** | 4.5 |
| label `#07090e` on identity fill `#ff7a1a` | **7.64:1** | 4.5 |
| focus ring `#ff7a1a` on card / plane (non-text) | **7.13 / 7.64:1** | 3.0 |
| input border `#8b949e` on card / plane (non-text) | **6.05 / 6.47:1** | 3.0 |
| status ok `#3fc79b` on card | **8.73:1** | 4.5 |
| status watch `#ffd166` on card | **12.90:1** | 4.5 |
| status alert `#f5514e` on card | **5.46:1** | 4.5 |
| chart severity blocking / warning / info | **5.46 / 12.90 / 8.65:1** | 3.0 |
| series-1 `#3987e5` / series-2 `#199e70` on card | **5.11 / 5.46:1** | 3.0 |

**Identity-vs-status separation (the collision test the survey asked for,
§6.5).** In dark, identity-orange `#ff7a1a` (7.13:1) sits **1.81× darker than**
watch-amber `#ffd166` (12.90:1) — a lightness channel that survives every CVD
type, on top of the hue difference. Against alert-red `#f5514e` the lightness
separation is 1.31× plus a clear hue split; and every status additionally ships
a distinct **shape** (octagon / triangle / circle) and a **word**, so no reader
depends on telling two warm hues apart. In light, the warning family always
renders as text-on-tint (`#664b00` on `#fff3d1`) with an icon, while
identity-orange only ever appears as a saturated fill or rule on a neutral
surface — the two never occupy the same encoding channel.

### 4. Screenshots (light + dark)

Captured from the **real component tree** (rendered via the real fixtures) with
the **real stylesheet**, photographed in headless Chrome at 1400px wide, at the
page's own content height. Under `docs/images/handoff-0041/`:

| File | What it shows |
| --- | --- |
| `dashboard-agency-light.png` / `-dark.png` | The default "All modes (agency)" view with the Mode selector in the control deck |
| `dashboard-bus-light.png` / `-dark.png` | Re-scoped to `mode:bus`: mode figures verbatim, scope receipts on every tile, mode-named heading, DQ card flagged and stating it is not narrowed |
| `dashboard-empty-light.png` / `-dark.png` | The per-mode empty state for `mode:subway` outside its dates — designed, warm, zero fabricated zeroes, DQ card still present and still flagged |

### 5. Deliberately deferred (with reasons)

1. **Overpass is not vendored.** The build makes zero external requests and a
   CDN font would break on-prem parity, so `--font-display` falls back to the
   industrial grotesques already installed on a Linux/macOS/Windows box. A
   `TODO` at the token sits in `styles.css`: self-hosting Overpass (OFL) the way
   the basemap vendors Noto is an **asset commit**, and when it lands it goes
   first in the stack and nothing else changes.
2. **Light-theme surfaces were not moved to a warm paper ground.**
   `--color-bg: #ffffff` / `--color-surface: #f6f8fa` are *pinned by the server*:
   `services/api branding.py` certifies every accepted agency brand color
   against exactly those two values. Changing them would silently invalidate a
   server guarantee — that needs a backend handoff, not a CSS edit. Noted in the
   token header.
3. **Light `--color-accent` stays the agency's brand accent.** Identity-orange
   is a separate token (`--signal`) in light; in dark the two converge because
   the dark accent has always been ours. So light mode still shows brand-blue
   links. Unifying them requires the server guardrail to certify orange — a
   backend handoff.
4. **The study's categorical mode-line hues** (`--m-fixed`, `--m-dar`, …) were
   **not** adopted: adding four more hues would be exactly the palette pileup
   the direction forbids. Mode identity is carried by words plus the mono scope
   receipt.
5. **Not built this wave** (survey §4 items that belong to other surfaces): the
   issue-ranked "needs investigation" worklist, the data-age stamp, honest Gantt
   bands, and the streamed provenance terminal. The data-quality card's alert
   rail is the first, smallest instance of the worklist idea.
6. **No temporal scrubber** on the metrics dashboard — per the handoff's scope
   note, that is the TOC replay dashboard's signature.

### 6. Open questions — answered where this wave could answer them

- **"Should the Mode selector and Audience lens compose freely?"** — **Yes, and
  they do.** No combination is hidden. The honest half is that surfaces without
  a mode dimension (operations metrics per route; DQ tallies per issue) *say* so
  under a mode rather than pretending to narrow.
- **"What is Arc?"** — still unknown, and now it does not block anything: the
  selector is data-driven, so Arc appears the day a `mode:Arc` scope is
  persisted, with no frontend change.
- **The `frontend_aesthetics` calibration note in
  `docs/design/claude-design-prompt.md`** — not written here; it is a docs-owned
  artifact and this wave stayed in its lane. The settled direction and the
  token table above are the raw material for it.
