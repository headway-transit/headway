# Claude Design prompt — Headway UI elevation

Paste into claude.ai/design (repo is connected; after the design-sync completes, the agent will also have our real components + tokens).

---

You are redesigning **Headway**, an open-source transit data platform whose product thesis is *radical provenance*: every displayed number can prove itself — coverage meters, documented exclusions, and the verbatim FTA regulation quoted inside the figure it governs, with a walkable lineage graph down to raw vehicle telemetry. The audience is transit agency staff (operations managers, data stewards, certifying officials — largely non-technical) plus their C-suite, boards, and the riding public.

**Your task:** audit and elevate the existing UI (GitHub repo connected — read `web/src/`). Identify friction points, unclear affordances, missing feedback states, and interactions that don't meet expectations for a design-focused audience. Then redesign. **Prioritize findings and fixes by impact on user experience, never by implementation complexity.**

**Hard constraints (non-negotiable, they are the product):**
- WCAG 2.1 AA floor on every surface — contrast, keyboard paths, focus visibility, screen-reader names. Beauty that fails accessibility is a regression here.
- Displayed figures are verbatim strings from the API — never reformatted, rounded, or recomputed in the UI.
- Provenance surfaces (the Receipt, the lineage walk, SIMULATED/pre-verification flags, the certification acknowledge gate) must become *more* prominent through redesign, not decoratively buried. The chain of custody is the hero.
- Data-encoding colors stay palette-validated (colorblind-safe, contrast-checked) and separate from brand chrome; agencies brand the chrome, never the charts.
- Plain language throughout: a transit operations manager must understand every screen.

<frontend_aesthetics>
You tend to converge toward generic, "on distribution" outputs. In frontend design, this creates what users call the "AI slop" aesthetic. Avoid this: make creative, distinctive frontends that surprise and delight. Focus on:

Typography: Choose fonts that are beautiful, unique, and interesting. Avoid generic fonts like Arial and Inter; opt instead for distinctive choices that elevate the frontend's aesthetics.

Color & Theme: Commit to a cohesive aesthetic. Use CSS variables for consistency. Dominant colors with sharp accents outperform timid, evenly-distributed palettes. Draw from IDE themes and cultural aesthetics for inspiration.

Motion: Use animations for effects and micro-interactions. Prioritize CSS-only solutions for HTML. Use Motion library for React when available. Focus on high-impact moments: one well-orchestrated page load with staggered reveals (animation-delay) creates more delight than scattered micro-interactions.

Backgrounds: Create atmosphere and depth rather than defaulting to solid colors. Layer CSS gradients, use geometric patterns, or add contextual effects that match the overall aesthetic.

Avoid generic AI-generated aesthetics:
- Overused font families (Inter, Roboto, Arial, system fonts)
- Clichéd color schemes (particularly purple gradients on white backgrounds)
- Predictable layouts and component patterns
- Cookie-cutter design that lacks context-specific character

Interpret creatively and make unexpected choices that feel genuinely designed for the context. Vary between light and dark themes, different fonts, different aesthetics. You still tend to converge on common choices (Space Grotesk, for example) across generations. Avoid this: it is critical that you think outside the box! Get inspiration from top rated transit applications that have received rewards on their UI.
</frontend_aesthetics>

**Deliver:** (1) a prioritized UX-audit findings list (impact-ranked); (2) redesigned key flows — Dashboard, the Receipt, the lineage walk, the certification cockpit, the public transparency page; (3) a motion/typography/color direction that makes provenance feel like craftsmanship — the aesthetic should whisper "audited, trustworthy, civic" while being genuinely distinctive. Any font or palette you propose must ship with its contrast math intact.
