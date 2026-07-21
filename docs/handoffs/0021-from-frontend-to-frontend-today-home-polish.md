# Handoff: design → frontend — The "Today" home + motion/material polish wave

## Context
Ease-of-use direction (project lead, 2026-07-20): draw users in the way best-in-class BI products do — the product greets you with YOUR situation — without ever compromising an honesty surface. Inspiration (not imitation): card-first landing, confident numbers, obvious next actions, micro-interaction polish, teaching empty states.

## Design (binding)
1. **/today — role-aware briefing home** (becomes the post-login landing; dashboard remains in nav): briefing cards composed CLIENT-SIDE from existing endpoints (the counts endpoints from handoff 0017 are built and unconsumed — consume them now: /dq/issues/counts, /safety/events/counts, /safety/deadlines, /certifications, /metrics/values, /reports surfaces). Role-aware composition: certifying_official leads with certification state ("July figures: N ready, M blockers open" → /certify) + deadlines; data_steward leads with DQ queue movement + newest refusals + attestation-eligible items; report_preparer leads with report/export readiness + sampling progress; everyone gets the KPI cards (latest figures w/ deltas via /metrics/compare) and ops cards (badged). EVERY number on a card keeps its receipt door. Cards state their data honestly (a card with nothing to say says so warmly, never invents urgency).
2. **Motion/material polish pass** (app-wide, small and disciplined): skeleton loading states replacing spinners on the main views; enter/transition micro-animations for cards, toasts, dialogs (150-250ms, CSS-first); hover/focus affordances on interactive cards; ALL behind prefers-reduced-motion (reduced = instant, never just slower); no motion on honesty-critical reveals (a refusal or FAILED verdict never animates in cutely — appears instantly, plainly).
3. **First-run guided tour**: a dismissible, restartable walkthrough (localStorage flag; "Take the tour" in the help/nav) that teaches THE THESIS interactively: land on /today → open a KPI card's receipt → dwell on the quote → walk lineage one step → done ("every number here can prove itself — now you know how to check"). Plain language, keyboard-accessible, no third-party tour lib unless license-gate-clean and genuinely better than a hand-rolled focus-managed overlay (prefer hand-rolled; it's 5 steps).
4. **Empty states that teach**: audit the main views (metrics before data, sampling with no plans, safety with no events, certifications with none) — each empty state gains one warm sentence + the concrete first action (link or command), house voice, never blank.
5. **Honest scope**: no layout redesign of existing views (polish, not upheaval); no new backend; the tour never blocks (skippable at every step); /today performance budget — first paint under 1s on the dev stack (compose requests in parallel, skeletons meanwhile).

## Outputs
/today + landing redirect, polish pass, tour, empty states; full web suite + axe (tour overlay included) + contrast + build; live click-through per role (three roles) with screenshots; evidence here.

## Open Questions
- Per-user card preferences/pinning (v1); briefing email/digest (never without explicit opt-in; future).

## Response (frontend, 2026-07-20)

Contract accepted and built, `web/` only. Deviations from the letter, none silent:

1. **report_preparer has no live demo account.** Creating one in the shared dev
   database was outside this wave's authorized scope (the environment's
   permission gate refused the insert), so the role is covered by the mocked
   suite (`web/src/test/today.test.tsx` — the preparer composition test) and
   live click-throughs cover the two roles that exist (`certifier`,
   `dsteward`). Anyone with DB access can create one the way
   `install/install.sh` does (bcrypt into `auth.users`, role
   `report_preparer`).
2. **`/dq/issues/counts` is consumed per-status only, never unfiltered** — a
   live finding, not a preference: on the dev box's 41,365-open-issue queue an
   unfiltered (or `status=open`) count takes ~4.6–5s SERVER-side, and the API
   serializes concurrent requests behind it (a sibling request measured at
   14s while a count ran). /today fires only the per-status counts each card
   needs (each scales with its own rows; owned/attested/resolved are
   milliseconds), the certification card renders its figures immediately and
   gives the blockers line its own one-line skeleton, and a regression test
   fails loudly if /today ever issues an unfiltered count. **Recommended
   Backend follow-up (no backend changes made here): index/optimize the DQ
   counts query and look at request concurrency in the API.**
3. **Delta lines name the compared period explicitly** ("238100 less than the
   previous period (2026-07-09 to 2026-07-10)"): the server compares whatever
   previous period exists, including one of a different length — the reader
   must see that at a glance, not discover it.
4. **Two live themed-chrome findings fixed in-wave:** the nav "Take the tour"
   button (a button, not an anchor) kept the accent-blue link color on a
   themed header — now takes the server-verified chrome header text color;
   and `/metrics/:id/lineage` (on the tour's walk path) still had a bare
   "Loading…" — it now has the same skeleton as the other main views.
5. **"Never blocks" implemented literally:** the tour is a NON-modal dialog —
   no backdrop, no focus trap; Escape leaves from anywhere; route steering
   happens once per step entry, so a user who navigates away mid-step is
   never yanked back (pinned by test).

## Outputs — evidence

Verified at commit `d37a933` + this working tree (uncommitted, per the
wave's no-commits rule), live vite dev server `localhost:5173` against the
live API `127.0.0.1:8000` and the live Compose TimescaleDB.

**Build + lint + contrast (all green):**

```
$ npm run build         → tsc -b && vite build … ✓ built (dist/assets/index-*.js ~606 kB)
$ npm run lint          → oxlint, no findings
$ npm run check:contrast → 81/81 PASS — "All token pairs meet WCAG 2.1 AA."
  (4 new registered entries for the tour panel border / target ring, both
  themes; skeleton fills are deliberately unregistered — decorative,
  aria-hidden, words carry the loading state)
```

**Test suite:** 210 tests / 32 files, all green (was 186/29 before this
wave — +24: `today.test.tsx` 12, `tour.test.tsx` 7, `emptyStates.test.tsx`
4, certifications empty-state +1; login/certifications updated for the new
landing + copy). Tour overlay, today cards (loaded AND skeleton states),
and the themed-chrome coexistence case are all axe-gated. Full-suite output
pasted below in "Suite run".

**/today first paint — the measured number (real browser, SPA nav
`/metrics` → `/today`, live API):**

```
domReady 20.3 ms · first frame PAINTED 35.6 ms (28 skeleton blocks visible)
→ the < 1 s budget is met ~28× over; requests are composed in parallel.
Full data settle: 11.1 s wall on THIS dev stack — dominated by the
backend's ~5 s open-issues count over the 41k-row live queue plus request
serialization (see Response #2), and inflated by React StrictMode's dev
double-fetch. The page is interactive throughout: KPI figures render as
their slices land; only late slices keep skeletons.
```

**Live click-throughs (headless Chrome via playwright-core, SPA-nav only
after login; screenshots in `docs/images/handoff-0021/`, full log in
`clickthrough-log.txt`):**

- `certifier` (certifying_official): tour AUTO-OFFERED on true first visit;
  walked end-to-end — step 2 opened the first KPI receipt (10 verbatim FTA
  quotes inside, live), step 3 ringed the quote, step 4 navigated through
  the receipt's own walk door to the lineage view, step 5 finished and set
  `headway-tour-seen=1`. Composition: Certification lead card ("July 2026
  figures: 91 computed and not yet certified." · "30 blocking data-quality
  issues open…" · "3 certifications on record.") + Safety card (20 events,
  12 major; 7 S&S-40s due; S&S-50 for 5 modes incl. zero-event rule) + KPI
  cards (VRM 160835.49 mi / VRH 16326.89 h verbatim, receipt doors) + badged
  ops cards (OTP 54.10, cvh 0.3010). Receipt → lineage walk clicked outside
  the tour too. Screenshots: `certifier-today.png`,
  `certifier-tour-step1..5.png`, `certifier-today-receipt.png`,
  `certifier-lineage.png`.
- `dsteward` (data_steward): DQ queue leads ("41,365 open and 0 owned
  issues… 30 blocking… 2 attested… 279 resolved" — all server-counted) +
  Safety + KPI + ops; NO certification card (asserted). Screenshot:
  `dsteward-today.png`.
- `report_preparer`: no live account (Response #1) — composition verified by
  the mocked suite: readiness tally ("1 of the 4 monthly report measures…")
  + sampling progress through the house RowProgress ("31 of 32 required
  units measured.").

**Reduced motion (emulated via CDP — `page.emulateMedia({ reducedMotion:
'reduce' })`):**

```
matchMedia(prefers-reduced-motion: reduce) = true
.skeleton  animationName = "none"   (control run without emulation: "hw-shimmer")
.anim-rise animationName = "none"   (control run without emulation: "hw-rise-in")
→ reduced = INSTANT, verified live both directions; screenshot
  certifier-today-reduced-motion.png
```

**Themed chrome + /today coexistence:** exercised live with `GET /branding`
intercepted client-side to serve a chrome set (`#0b3d2e`/`#f2fbf7`/
`#7fe0b7`) — nothing written to the shared database. Result:
`data-chrome="on"`, header background `rgb(11, 61, 46)` verbatim, briefing
cards and receipt doors untouched (screenshot
`certifier-today-themed-chrome.png`); also pinned by a unit test asserting
the `--chrome-*` variables + the intact receipt door under chrome.

**Binding rules, where they are enforced:**

- Every card number keeps its receipt door — figures are buttons disclosing
  the full house Receipt inline (lineage walk inside); workflow tallies link
  to exactly the list the server counted (the 0017 counts endpoints count
  over exactly the rows those lists serve). Pinned in `today.test.tsx`.
- Cards never invent urgency — every empty state is a warm statement
  (`copy.today.*`), and the empty-board test asserts NO `role="alert"`
  appears on an empty /today.
- Refusals/FAILED verdicts never animate — no animation class on
  `.alert`/`.banner`/`.certificate-failed`, plus a CSS `:has()` guard
  stripping card-enter animation from any card arriving with an alert.
- All motion behind `prefers-reduced-motion`, reduced = instant (verified
  live above; CSS-only, 150–250 ms).
- Tour: hand-rolled (no library — nothing new in package.json), skippable
  at every step + Escape-from-anywhere, keyboard-accessible (focus follows
  the step headings), non-modal/never blocks, honest no-target fallback on
  an empty board. All pinned in `tour.test.tsx`.
- No backend changes: `services/`, `db/`, `install/`, `deploy/`,
  `.github/` untouched (`git status` shows web/ + docs evidence only).

**Suite run (paste, 2026-07-20 20:02 local):**

```
 RUN  v4.1.10 /home/daniel/headway/web
 Test Files  32 passed (32)
      Tests  210 passed (210)
   Duration  69.78s
```
(A first full-suite run DURING the live click-throughs showed 8
timeout-flakes in long interactive tests — the box was running two dev
servers, headless Chromes and parallel vitest workers; all 8 files pass in
isolation and the final quiet-box run above is green. Recorded honestly,
not hidden.)
