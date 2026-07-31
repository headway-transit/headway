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
