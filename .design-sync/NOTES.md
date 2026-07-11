# design-sync NOTES — Headway web

- App repo (not a library): synth-entry from src/components (srcDir) — main.tsx/views MUST stay out of the sweep (main.tsx's createRoot throws on blank pages and kills the bundle IIFE).
- web/node_modules/web self-symlink (`ln -sfn .. web/node_modules/web`) required for the converter to resolve the package; recreate on fresh clones (gitignored).
- Props interfaces must be EXPORTED in source; extraction still stubs in synth mode → dtsPropsFor carries all 9 contracts by hand. Keep them in sync with source (SeverityStackedBar drifted once: segments also need displayCount + color).
- react-router context: DesignSyncProvider (web/src/design-sync-provider.tsx, MemoryRouter) via extraEntries + cfg.provider — Receipt/Layout/LineageGraph links need it.
- SeverityIcon inherits currentColor by design — previews must wrap in the app's `chip severity <sev>` classes or it renders monochrome.
- Modal is position:fixed — cardMode "single" override required.
- Receipt copy interpolates detail.missing_trip_threshold — fixtures must include it or the sentence reads "when % or fewer".

## Known render warns
- Modal capture sheet clips the dialog top (h2/figure) — focus-trap anchors the fixed overlay at the textarea in the harness; NOT an app defect (live-proven). 3 iterations recorded; accept the sheet.

## Re-sync risks
- dtsPropsFor is hand-maintained: any component API change in web/src/components must be mirrored there (validate catches nothing for this — it's the design agent's contract).
- Preview fixtures embed real figures (12794.92 etc.) as REALISTIC DATA — they don't rot, but new calc versions may make calc_version strings stale-looking.
- TimeSeriesChart yTop-clamp bug found by preview verification 2026-07-11; fixed in source — if reverted, CoverageWithThreshold/DailyUpt previews will silently clamp again.
