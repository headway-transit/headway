# Headway → RouteSight: the mechanical rename checklist

Companion to ADR-0014 and `2026-08-02-routesight-trademark-screen.md`.

This exists so the rename is a list to work through rather than a discovery
exercise done under time pressure. Nothing here is authorised until the gates
below are passed.

## Gates — in this order, no overlapping

1. **Clearance.** A knockout + clearance search comes back acceptable. Until
   then the name goes nowhere public. Renaming to a name that later fails
   clearance is strictly worse than staying on Headway.
2. **Domains registered.** `.io` and `.org` at minimum; decide on `.com`
   (HugeDomains reseller, so it has a price rather than an owner). `.co`,
   `.app` and `.dev` are still **unverified**, not known-free.
3. **One rename event.** Do not split it across weeks. Two names live in
   public for a month is worse than either name alone.

## Do NOT rename these

The sharp edge of this job. "Headway" is also the correct transit word for the
interval between vehicles, and this product *measures* it.

- **`headway_adherence_v0`** — a shipped calc name, persisted in `metric_value`
  rows and mapped in `services/calc/headway_calc/persist.py:81,96`. Renaming it
  breaks the retained-runnable guarantee and orphans already-certified figures.
  **It stays, permanently, in a product called RouteSight.**
- **`headway_adherence`** — the metric name it writes. Same reason.
- The word "headway" in operational definitions, `OPS_DEFINITIONS.md`, the
  notebooks (`02-otp-headway-adherence.ipynb`), and any user-facing text where
  it means *the interval between vehicles*.

~550 tracked files contain the string; roughly 27 of them mean the transit
term. **A global `sed` corrupts the domain vocabulary.** Work by category, not
by regex.

## One-way doors — get these right the first time

| Surface | State today | Action |
| --- | --- | --- |
| **PyPI** | `headway-client` **never published**; `routesight`, `routesight-client` free | Publish only under the new name. This is the one genuinely irreversible namespace and it currently costs nothing — the single luckiest fact about the timing |
| **GitHub org** | `headway-transit`, created 2026-07-09, 0 followers, 1 repo | **Rename in place.** Redirects are permanent — *until someone claims the freed name*. Re-register `headway-transit` as a placeholder the same day, or the redirect dies and the old name is impersonable |
| **GitHub repo** | `headway`, 1 star, 0 forks, 0 issues, 7 PRs, 2 releases | Rename. Preserves history, PRs, releases, and the links in the published Bluesky threads |
| **Bluesky** | `@headway-transit.bsky.social`, created 2026-07-12; threads posted 07-12 and 07-14 | Handle change preserves followers and posts (already researched in `docs/announce/bluesky.md`). Hold the old handle — it becomes claimable |

## Internal mechanical work

**Go module path** — `github.com/headway-transit/headway/services/ingestion`.
Load-bearing: every import across the Go code carries it. Change with the org
rename, in one commit, `go mod edit -module` plus a mechanical import rewrite.

**Python packages** — six, each with an `.egg-info` to regenerate:

```
clients/python/headway_client     services/api/headway_api
services/ai/headway_ai            services/calc/headway_calc
services/mcp/headway_mcp          services/transform/headway_transform
```

**Container images** — `ghcr.io/headway-transit/headway-{ingestion,transform,api,web}`,
pushed on release by `.github/workflows/release.yml:171` and referenced in
`deploy/compose/compose.yaml:308-531`. GHCR package paths follow the org
rename; old pull paths break. Only two alpha releases exist, so **re-cut a
release under the new name** rather than trying to preserve old paths.

**Docs and chrome** — README badges (shields.io URLs embed the repo path),
`docs/announce/`, `HANDOFF.md`, `ROADMAP.md`, `SUPPORT.md`, installer
user-facing strings, and the repo description.

## Operator-facing — needs a compatibility window

At least twelve `HEADWAY_*` environment variables live in operators' own
`deploy/compose/.env` files:

```
HEADWAY_ACCESS_MODE      HEADWAY_ADMIN_PASSWORD   HEADWAY_ADMIN_USERNAME
HEADWAY_AGENCY_ID        HEADWAY_COMPOSE_DIR      HEADWAY_COMPOSE_PROJECT
HEADWAY_CORS_ORIGINS     HEADWAY_DATABASE_URL     HEADWAY_IMAGE_TAG
HEADWAY_GTFS_STATIC_URL  HEADWAY_GTFS_RT_VEHICLE_POSITIONS_URL …
```

Renaming these silently breaks every existing install on upgrade. **Accept both
prefixes for one release**, log a plain-language deprecation warning naming the
old and new variable, then drop the old prefix a release later. The audience is
the zero-SQL, one-week-Linux operator: a failed boot with a missing-variable
stack trace is not an acceptable upgrade experience.

## Announcement

The old name is in two published Bluesky threads that cannot be silently
rewritten. The rename gets a plainly-worded post saying what changed and why —
a collision with an active OSM project, not a rebrand for its own sake.

One casualty worth noting: the 2026-07-14 thread's line *"the platform named
Headway finally measures headway"* stops working. It was a good line. It does
not survive, and pretending otherwise in a rewritten thread would be the kind
of quiet edit this project does not do.
