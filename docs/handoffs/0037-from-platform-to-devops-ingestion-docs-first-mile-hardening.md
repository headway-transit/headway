# Handoff: platform → devops+ingestion+docs — First-mile hardening (simplify the first mile)

## Context

Daniel's standing direction (2026-07-30): **adoption must survive a general audience.**
Every item below is a real failure from this week's partner-agency work, not a
hypothetical — the installer's first users are an expert-in-transit-data ITS manager
with one week of Linux and zero SQL, and an agency with no DBA. The failures:

- `.env` hand-typos found live: `Rrealtime` in a pasted URL, `https//` missing the
  colon. The pipeline then fails downstream, silently from the operator's chair.
- The vendor-drop first APC ingest was blocked by permission-denied: the connector
  runs as uid 65532 (distroless nonroot) and could not create/write `processed/`
  under a host-owned drop dir. Interim advice was `chmod 777` — beneath the platform.
- Excel round-trip mangled a vendor CSV's dates (also bit us on 2026-07-16).
- Every SQL instruction we send the agency must assume SSMS click-paths, not typed
  SQL (BFT has no DBA; Tony is the process expert being trained up).

## Design (binding)

1. **Installer validates feed URLs at entry.** When a URL is typed/pasted into the
   install prompt (and `--reconfigure`-style paths): (a) **syntax check** — scheme
   present and well-formed (`https//`-class typos caught by name: say "there's a
   colon missing after https", not "invalid URL"); (b) **live check, with consent** —
   the installer already asked for the URL, so fetching it is expected, but say
   "Checking the feed…" first; static feed must respond and look like a ZIP,
   realtime must respond and parse as a GTFS-Realtime FeedMessage (magic-bytes/
   protobuf sniff is enough at install layer — no new heavy deps in bash; `curl` +
   file signature checks; for RT, accept content sniff over full protobuf parse if
   that is what bash can honestly do, and record the limitation). (c) On failure:
   plain words, what was checked, likely cause ("this address answered with a web
   page, not a schedule file — check for a typo"), and **offer re-entry**; never
   write a failed URL to `.env` without an explicit "keep it anyway" confirmation.
2. **`--check-feeds` subcommand:** validates whatever feeds `.env` currently holds,
   same checks, same plain language, exit nonzero on failure. This is the command
   support tells an agency to run first, and the updater's post-update health check
   may call it.
3. **Drop-dir ownership created correctly.** Installer and `--update-from-source`
   create `TIDES_DROP_DIR`/`VENDOR_DROP_DIR` (when configured) **and their
   `processed/` subdirectories** with ownership/permissions the uid-65532 container
   can write (chown to 65532 or group-writable — pick the least-privilege option
   that works on a plain Ubuntu host and record why). Retro-fix path: the updater
   detects wrong ownership on existing dirs and offers the fix.
4. **Every permission error prints its exact fix command.** The vendorfile/tides
   connectors' permission-denied paths (create `processed/`, move file, read drop
   file) must print the *actual paths involved* and the *exact command* that fixes
   them (e.g. `sudo chown -R 65532:65532 /srv/headway/vendor-drop`), plus one line
   of why ("Headway's collector runs as a locked-down user that cannot read files
   owned by root"). No generic `permission denied` ever reaches the operator bare.
   Never advise 777.
5. **Excel warning where CSVs are handled.** `docs/connecting-your-data.md` (drop-dir
   section) and any doc that tells an agency to export/inspect a CSV gains a short,
   friendly warning box: opening a CSV in Excel and saving it silently rewrites
   dates and strips leading zeros; look with a text editor or make a copy. Include
   the one-sentence why. (In-app upload with server-side validation is ROADMAP, not
   this wave — but add it to ROADMAP.md if not already there.)
6. **SSMS click-paths + view-DDL generator for the zero-SQL audience.** A small
   generator (suggested `tools/view-ddl/`, language your call — must run with zero
   extra install steps for us, and its OUTPUT is what travels) that takes an adapter
   spec / column contract and emits: (a) the full `CREATE VIEW` DDL (the
   `vw_headway_apc` pattern — explicit column list, `CONVERT` ISO dates baked in,
   never `SELECT *`), (b) the `headway_ro` login + grant statements, and (c) a
   **click-path document**: numbered SSMS steps ("open SSMS → connect → right-click
   Databases → New Query → paste → Execute → you should see 'Commands completed
   successfully'") written for someone who has never run SQL, including how to send
   the output back. Verify the generated DDL parses (sqlcmd against a disposable
   mssql container via `sg docker -c`, the 0033 precedent — if the container won't
   run on this box, say so and pin by golden-file tests).
7. **Feed auto-discovery wizard — nobody should type a URL.** Installer flow (also
   reachable later via a flag, e.g. `--discover-feeds`): ask for the agency's name
   (and state/region if needed to disambiguate), then — **consent before contact**,
   the `--download-basemap` precedent: name the exact external service before
   touching the network — query the MobilityData mobility-database catalog
   (registry-first; pin how the catalog is fetched and from where), match candidate
   feeds, **live-verify each candidate with the design-point-1 checks before
   offering it**, present verified feeds in plain words ("Found your agency's
   schedule feed and a live vehicle-positions feed, both responding") and write
   `.env` only on the operator's yes. Misses are honest: "couldn't find your agency
   in the public registry — here's how to ask your vendor for the URLs" (link the
   doc). **No AI crawling in v0** — registry only; the AI-crawl fallback stays
   ROADMAP under the grounding contract. Deprecated-URL trap from the BFT crawl
   (multiple registry entries, older ones dead) must be handled: prefer entries that
   live-verify; never offer a dead one.

## Coordination note

A concurrent wave (handoff 0036) is adding MinIO env wiring for the gtfsrt connector
to `deploy/compose/compose.yaml` and possibly `install/install.sh`. Keep your edits
localized and additive; the orchestrator integrates both.

## Outputs

`install/install.sh` changes (validation, `--check-feeds`, drop-dir ownership,
wizard) with the installer's existing self-test/refusal-path style of verification —
live-run the refusal paths and the wizard on this box (the BFT feeds and MBTA feeds
are known-good registry entries to test against, but never write agency names into
committed fixtures); connector error-message changes + Go tests; the view-DDL
generator + tests + a generated sample pack (sanitized column names only);
docs updates (Excel warning, wizard doc, click-path doc template); ROADMAP.md
updates for the deferred pieces; evidence appended here (transcripts of the live
checks, including at least one deliberately-broken URL, one permission-denied fix
printout, and one full wizard run). No commits — the orchestrator integrates.

## Open Questions

- Should `--check-feeds` also verify feed *freshness* (RT header timestamp age) or
  only reachability/shape? (Freshness is a pipeline concern too — DQ owns it there.)
- In-app CSV upload with validation (Excel-proofing at the source) — ROADMAP timing.
- Wizard v1: AI-crawl fallback for registry misses under the grounding contract;
  auto-configuring TripUpdates/ServiceAlerts alongside VehiclePositions when present
  (v0 should already offer all three when the registry has them — record what v0
  actually does).
