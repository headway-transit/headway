# Handoff: frontend-engineer → frontend-engineer, backend-engineer — Visual identity: modern UI, dashboards, agency branding

## Context
First-user critique (certifying official, 2026-07-11): the platform does its job but doesn't *invite* — people expect clean, modern, visually appealing; agencies want their own logos and colors; the data deserves graphs. This handoff makes beauty a governed feature, not taste.

## Pillars (binding)
**A. Visual refresh.** Modern, calm aesthetic: typographic scale, generous spacing, card surfaces with subtle elevation, refined nav. Existing AA-validated tokens remain the base; every new color pair passes the contrast gate. No decoration that obscures data.

**B. Dashboards (dataviz method — MANDATORY).** New /dashboard view. Charts follow the loaded dataviz discipline exactly:
- Forms by data job: daily UPT → line w/ crosshair+tooltip; VRM/VRH trend → lines (ONE axis each — never dual-axis; two measures = two charts/small multiples); coverage over time → line with threshold reference line; DQ open issues by severity → stacked thin bars w/ 2px surface gaps; headline stat tiles (latest certified figures) as hero numbers.
- Categorical hues in FIXED order, never cycled; sequential = one hue light→dark; status colors reserved (never "series 4"), always icon+label.
- **Palette must be VALIDATED, not eyeballed**: run `node <dataviz-skill>/scripts/validate_palette.js "<hexes>" --mode light` (and --mode dark against the dark surface) — fix FAILs before shipping; CVD ≥ 12 target; a contrast WARN obligates direct labels/table view.
- Every chart: hover layer, legend for ≥2 series (≤4 also direct-labeled), recessive grid, text in text tokens never series color, and an accessible table-view toggle.
- Values remain verbatim strings in tooltips/labels; chart geometry may scale, displayed figures never recomputed.

**C. Agency branding — with the guardrail.** Agencies set display name, primary/accent brand colors, and a logo. THE HEADWAY TWIST: **the server refuses colors that fail WCAG AA against our surfaces** (contrast math computed server-side, plain-language 422: "That color doesn't have enough contrast to be readable…"). You can brand it; you cannot brand it inaccessible.
- Backend: migration 0015 seeds settings keys `agency_display_name` (text), `brand_color_primary`, `brand_color_accent` (text, hex-validated + AA-validated on PUT vs light & dark surfaces); `POST /branding/logo` (admin, multipart, size/type-limited (SVG/PNG ≤ 512 KiB), stored to MinIO `branding/logo`, served via `GET /branding/logo` unauthenticated with cache headers); audited.
- Frontend: a Branding settings page (admin) with live preview + the refusal messages surfaced; app shell consumes name/colors/logo via CSS custom-property overrides layered over base tokens; charts do NOT take brand colors (dataviz palette is validated separately — brand ≠ data encoding).

## Sequencing
Backend pillar-C half may start immediately (services/api + migration — no web conflict). Web pillars A/B + branding UI start ONLY after wave 14 (click-through fixes) lands in web/.

## Verification
Suites green (api, web incl. axe on all new surfaces); palette validator output pasted for light AND dark; contrast-refusal tested server-side (a failing hex → 422) and shown in UI; branding preview keyboard/axe clean; anti-patterns checklist reviewed per chart.

## Response — backend-engineer (pillar C backend half, implementation evidence, 2026-07-11)

**Delivered** (services/api + db only; web/ untouched per sequencing):

1. **Migration `db/migrations/0015_branding_settings.sql`** seeds four `app.settings` keys (seeded, never client-creatable — unknown key stays 404): `agency_display_name` = 'Transit Agency' (text), `brand_color_primary` = '#1a5fb4' (text), `brand_color_accent` = '#0b57d0' (text, the base design-token accent), `brand_logo_meta` = 'unset' (text, system-maintained). Every description is plain language and the color keys carry the guardrail promise verbatim: "colors that fail accessibility contrast are refused". Registered in `db/test_migrations_static.py::test_branding_settings_seeded_with_contrast_guardrail`.

2. **`headway_api/branding.py`** — pure WCAG math, formula source VERIFIED against the published spec (fetched 2026-07-11), cited in the docstring, never from memory: relative luminance `L = 0.2126R + 0.7152G + 0.0722B` with piecewise sRGB linearization (`c/12.92` for `c <= 0.04045`, else `((c+0.055)/1.055)^2.4`) per WCAG 2.1 dfn-relative-luminance as reproduced in W3C technique G18 — the 0.04045 threshold is the May-2021 errata correction of the original 0.03928 (numerically identical for 8-bit channels; we implement the corrected constant); contrast ratio `(L1+0.05)/(L2+0.05)` per dfn-contrast-ratio (range 1–21); 4.5:1 = SC 1.4.3 AA.

3. **The surfaces — a binding math finding.** `LIGHT_SURFACE = #ffffff` (`--color-bg`) and `DARK_SURFACE = #f6f8fa` (`--color-surface`), both cited from `web/src/styles.css` `:root` (the only surfaces the web ships; single light theme per that file's header). The handoff's "light & dark surfaces" CANNOT mean a true dark-theme surface: no color reaches 4.5:1 against both `#ffffff` (needs L ≤ 0.1833) and any surface with luminance > 0.00185 (~`#060606`) — the dataviz dark chart surface `#1a1a19` (L ≈ 0.0103) is far above that bound. Derivation documented in `branding.py`. **Consequence for web pillars A/B: a dark theme needs a per-mode brand variant validated against its own surface; one stored color cannot serve both modes.**

4. **`PUT /settings/brand_color_*`** (routers/settings.py) now runs hex-format + contrast validation: a failing color is a plain-language 422 naming the failing surface and the measured ratio (e.g. `#aabbcc` → "…measures 1.96:1 against the app's page background (#ffffff)…at least 4.5:1 (WCAG 2.1 AA)"); a passing color persists with old→new audited as before. `brand_logo_meta` refuses direct PUT (422 → "upload via POST /branding/logo"). All other keys byte-for-byte unchanged behavior.

5. **`routers/branding.py`**: `POST /branding/logo` (certifying official, multipart; whitelist `image/svg+xml`/`image/png` else 415; > 512 KiB → 413; stored via the ObjectStore seam to `branding/logo` BEFORE the settings-row+audit transaction commits; audited `branding_logo_uploaded` with content_type/bytes/object_key; 503 when no store — never a silent accept). `GET /branding/logo` — unauthenticated, per-IP rate limited (the public open-data bucket), served with stored content type + `Cache-Control: public, max-age=300` + `nosniff` + a script-blocking CSP for SVG (defense against SVG-script on direct navigation); plain-language 404 while unset. `GET /branding` — unauthenticated `{display_name, primary, accent, has_logo}` for the app shell. `MinioObjectStore.get()` added in ingest.py for production parity; `FakeObjectStore.get()` in conftest. `python-multipart` (Apache-2.0) added to deps for the multipart parse.

6. **Tests** (27 new in `tests/test_branding.py`, fakes only): math pinned to W3C-published values (white/black exactly 21, same-color exactly 1, pure-primary luminances = the published coefficients) plus a cross-implementation check against `web/scripts/check-contrast.mjs`'s documented ratios (15.80, 6.39); failing hex → 422 with ratio + surface, nothing persisted/audited; a color passing white but failing the card surface names the card surface (`#767676` → 4.27:1); passing hex persists + audited; logo happy/oversize(413, nothing stored)/exact-512-KiB/wrong-type(415)/empty(422)/403/401/no-store-503; GET logo unauth 200 with headers, 404 unset, SVG CSP, 429 rate limit; GET /branding defaults + reflects changes.

**Verification (real output):**
```
$ cd services/api && python3 -m pytest tests/ -q
123 passed, 1 warning in 3.46s          # 96 pre-existing + 27 branding — all green

$ python3 scripts/export_openapi.py
Wrote services/api/openapi.json — OpenAPI 3.1.0, 17 paths: /auth/login, /branding,
/branding/logo, /certifications, /dq/issues, /dq/issues/{issue_id}/resolve,
/ingest/tides/passenger-events, /machine/keys, /machine/keys/{key_id},
/machine/metrics, /metrics/values, /metrics/values/{metric_value_id}/lineage,
/public/metrics/certified, /settings, /settings/{setting_key}, /webhooks,
/webhooks/{subscription_id}

$ cd db && python3 -m pytest test_migrations_static.py -q
14 passed in 0.11s
```

Default colors' measured ratios (documented in the migration): `#1a5fb4` → 6.29:1 on `#ffffff`, 5.91:1 on `#f6f8fa`; `#0b57d0` → 6.39:1, 6.00:1.

**For the web half:** consume `GET /branding` + `GET /branding/logo` (both public, per-IP limited); surface the 422 `detail` verbatim in the branding page (it already names surface + ratio in plain language); note point 3 above before building any dark-mode preview. README section added (`services/api/README.md` § Agency branding). Live-stack (real MinIO/Postgres) verification remains pending, as for all prior slices.
