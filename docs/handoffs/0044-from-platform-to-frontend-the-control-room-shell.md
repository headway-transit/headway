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
