# Handoff: devops → devops — The update story: upstream dependency flow + agency-side --upgrade

## Context
Project lead question (2026-07-20): how do dependency/security updates get packaged? The architecture answer is already charter: agencies never update dependencies in place — they replace signed images atomically. This wave builds both halves of that answer.

## Design (binding)
1. **Upstream flow (repo side):** (a) Renovate config (or Dependabot if Renovate needs external services conflicting with the first-party-only CI policy — evaluate, document choice): grouped weekly dependency PRs across go.mod/pyproject/package.json/Dockerfiles, auto-labeled, gated by the FULL existing CI (suites + license gate + drift gates + sbom/vuln scan) — no auto-merge in v0. (b) A scheduled weekly workflow: rebuild all five images from the latest release tag, Grype-scan them, and open an issue (or fail loudly) when a base-layer fix is available that the current release lacks — the "your published images have known-fixed CVEs" alarm. First-party actions only per CI policy.
2. **Agency side — `install.sh --upgrade`:** plain-language, installer voice: check current vs target release (explicit tag argument or latest from the GitHub releases API — the query happens ONLY when the admin runs the command; no phone-home ever, restated in docs); **cosign-verify every new image signature BEFORE anything switches** (keyless verify against the repo identity; refuse loudly on any mismatch); pull; swap tags in .env/compose; run migrations via the throwaway container (idempotent runner); health-gate all services; print a rollback section (previous tags recorded; data volumes untouched — state plainly that migrations are forward-only and rollback of the DB schema is NOT offered, the honest posture; app-image rollback is). `--check-updates` = read-only variant printing current vs latest + release notes URL. Respect the LAN/localhost access mode across upgrade (re-read the 0016 wiring).
3. **docs/updating.md**: the agency-facing story in plain words — what an update is (new signed images), how often to expect them, security-update policy (what triggers a patch release), the exact two commands, what happens to their data (nothing), and the no-phone-home commitment.
4. **Honest scope:** no auto-update daemon (deliberate — agencies control change windows; documented); no delta/canary machinery v0.

## Outputs
Renovate/dependabot config + scheduled rebuild-scan workflow (yaml-validated; workflows exercised as far as runnable without a release event — document what CI will prove on first scheduled run), --upgrade + --check-updates live-verified on a DISPOSABLE compose project on this box (upgrade path exercised against the real ghcr v0.2.0-alpha signed images incl. a real cosign verification; do NOT disturb the live demo stack), docs/updating.md, cross-links (README, install/README, network-access), evidence here.

## Open Questions
- Auto-merge for patch-level dep updates once trust accrues; canary/staged rollout for multi-box agencies (v1+); in-app "update available" surfacing (needs the opt-in check — Backend/Frontend later).
- **NEW (blocking the agency story, owner action needed):** the five ghcr packages are PRIVATE — see Outputs — evidence, finding 1.

## Outputs — evidence

Verification run 2026-07-20, working tree at commit `3690dba` (+ this wave's uncommitted changes). Environment: no-Docker-group shell (`sg docker -c`), live demo stack (compose project `headway` + API :8000 + vite :5173) protected throughout — baseline/after proof at the end. cosign v3.1.2 installed for verification from the official release binary into the session scratchpad, checksum-verified (`cosign_checksums.txt`: `cosign: OK`).

### Finding 1 (top finding, blocks the agency-facing half until fixed): the ghcr packages are private

Anonymous ghcr pull-token grants return 401 for ALL five packages:

```
headway-ingestion anon-token: 401     headway-api anon-token: 401
headway-transform anon-token: 401    headway-ai anon-token: 401
headway-web anon-token: 401
```

and the box's gh token lacks `read:packages` (manifest GET → 403 even authenticated). Consequences, stated plainly: (a) no agency can pull a release image today; (b) `cosign verify` cannot fetch signatures from the registry, so the planned green `--upgrade` transcript is impossible from this box — the installer instead refuses, loudly and correctly (transcript below). **Owner action:** flip each of the five packages public in GitHub package settings (UI only — visibility is not settable via the REST API), then re-run the disposable transcript (exact commands in "What remains unproven" below).

### Deliverable 1 — Renovate vs Dependabot: Dependabot, reasoning recorded

`.github/dependabot.yml` (full reasoning in its header + `docs/supply-chain.md` "How updates flow"): Renovate's zero-infra form is the Mend-hosted third-party app holding repo write access — what the first-party-only policy exists to refuse; self-hosting it adds always-on infrastructure for grouping features v0 does not need. Dependabot is GitHub-native (same trust boundary the project already stands on), grouped weekly PRs per ecosystem (gomod, pip×6 dirs, npm, docker×5 Dockerfile dirs, github-actions), `dependencies` label, **no auto-merge**. Honest limit recorded: Dependabot is first-party but not self-hostable; it is the component to replace if the project ever leaves GitHub. Compose infra image pins deliberately excluded (operational upgrades, not library bumps — per the handoff scope list).

### Deliverable 2 — scheduled scan workflow (`.github/workflows/rebuild-scan.yml`)

Weekly cron + `workflow_dispatch` (tag input for dry-runs). **Deliberate deviation from the Design's "rebuild then scan" wording, with reasoning** (recorded in the workflow header): scanning a fresh rebuild under-detects — rebuilds pick up patched base layers (apk/apt upgrades, moving base patch tags) and can scan clean while the published artifact agencies pull stays vulnerable. The alarm therefore Grype-scans the five **published** images at the latest release tag under the same `.grype.yaml` policy as the release gate (won't-fix excluded ⇒ remaining findings are fixable), fails loudly, and opens/updates an alarm issue via gh CLI (no third-party action); the rebuild is the documented *remediation* (patch release re-runs the full release gate). yaml.safe_load-valid (below). What only the first real scheduled run can prove: the cron actually firing (and GitHub's 60-day-inactivity auto-disable — a quiet repo silences its own alarm), GITHUB_TOKEN/issue-write from a schedule context, and Grype's ghcr pull inside the runner — which today would ALSO fail on finding 1 until the packages are public.

### Deliverable 3 — `--check-updates` + `--upgrade` (installer), tags-in-.env mechanism

Smallest honest change for images-built-locally → images-by-tag: `HEADWAY_IMAGE_TAG` in `.env` (default `local` = today's behavior), interpolated into the `image:` of ingestion/transform/api in `compose.yaml`; `web` deliberately stays a local build (its API origin is baked at build time — the released same-origin bundle would break both the `local` and `lan` layouts), so `--upgrade` rebuilds web from the release's source with the .env's address preserved (0016 access wiring untouched by construction). Hazard documented in compose/.env.example/README: with a release tag set, never `up --build`. Drift proof — old vs new `compose.yaml` rendered with identical env (`docker compose config`, synthetic secrets), app profile on:

```
199a200
>     image: ghcr.io/headway-transit/headway-ingestion:local
```

i.e. the ONLY effective change for existing installs is ingestion's now-explicit image name (its next `up --build` recreates it under that name — one-time, harmless). Test seams added to the installer (`HEADWAY_COMPOSE_DIR/_COMPOSE_PROJECT/_LOG_FILE`, `HEADWAY_NETWORK` in compose, `HEADWAY_UPGRADE_REPO` fork/identity seam — commented as such in the script; identity and release-list repo move TOGETHER so a wrong identity can never be paired with the right repo silently).

### Live transcripts (real GitHub releases API, real cosign, disposable project `hwdisp0022`)

Disposable harness: `deploy/compose-disposable-0022/` — byte-copy of `compose.yaml` + an override resetting all host ports and renaming the web image + its own `.env` (`HEADWAY_IMAGE_TAG=v0.2.0-alpha`, `HEADWAY_NETWORK=hwdisp0022`, synthetic secrets). Rendered config verified: images `ghcr.io/headway-transit/headway-{ingestion,transform,api}:v0.2.0-alpha`, network `hwdisp0022`, project-scoped volumes, **0 published host ports**.

**T1 `--check-updates` (disposable, tag recorded):** real API answered; printed `running: v0.2.0-alpha / newest: v0.2.0-alpha / You are on the newest release. Nothing to do.` exit 0.

**T2 `--check-updates` (LIVE install, read-only):** `running: built from the source code on this computer (no release version recorded) / newest: v0.2.0-alpha` + release-notes URL + upgrade hint; exit 0; live `.env` sha256 identical before/after (read-only proven).

**T3 `--upgrade` (disposable, no version):** resolved `v0.2.0-alpha` from the live releases API → same-tag re-apply NOTE → source-tree mismatch WARNING with exact fix commands + confirmation prompt (answered yes) → `OK cosign is installed (v3.1.2)` → real `cosign verify` against ghcr → **loud refusal** (private packages, finding 1): "The signature on ghcr.io/…headway-ingestion:v0.2.0-alpha did NOT verify. Headway REFUSES to install it, and nothing on this computer has been changed… please report it (SECURITY.md) — do not work around it." exit 1. Proven after refusal: disposable `.env` checksum unchanged; **0 containers** created for project `hwdisp0022`. (An unverifiable signature and a bad signature correctly get the same refusal: unverifiable IS unverified.)

**T4 wrong-identity refusal:** (a) installer run with `HEADWAY_UPGRADE_REPO=example/not-headway` → same refusal path, expected-signer line names the wrong repo (the seam threads through to verification); (b) because the registry blocks signature fetch before identity evaluation, the identity check itself was proven against the REAL signing certificate recovered from Rekor: SAN `https://github.com/headway-transit/headway/.github/workflows/release.yml@refs/tags/v0.2.0-alpha`; installer's exact-tag regexp → MATCH; deliberately-wrong-repo regexp → NO MATCH (refuses).

**T5 guards:** `--check --upgrade` combined → refused (exit 1); bare `v0.2.0-alpha` without `--upgrade` → helpful refusal (exit 1); `--upgrade v0.2` malformed → refusal (exit 1); `--help` renders (exit 0); `--reconfigure-access --yes` regression check on the disposable `.env` → "matches what was already set up, nothing needs to change", 0016 keys intact (`HEADWAY_ACCESS_MODE=local`, `VITE_API_BASE_URL=http://localhost:8000`, `COMPOSE_PROFILES=app` preserved alongside `HEADWAY_IMAGE_TAG=v0.2.0-alpha`).

### Real signature verification (transparency log — the half not blocked by finding 1)

From the actual v0.2.0-alpha release run (run 29180804264, per-image job logs): the five signed digests + Rekor tlog indices. For EACH of the five images, from the PUBLIC Rekor log (`rekor.sigstore.dev`), with cosign's SimpleSigning payload reconstructed byte-for-byte from the image digest:

```
headway-api        payload-hash:MATCH  sig:Verified OK  (logIndex 2148268291)
headway-ingestion  payload-hash:MATCH  sig:Verified OK  (logIndex 2148268433)
headway-transform  payload-hash:MATCH  sig:Verified OK  (logIndex 2148268217)
headway-ai         payload-hash:MATCH  sig:Verified OK  (logIndex 2148268188)
headway-web        payload-hash:MATCH  sig:Verified OK  (logIndex 2148268218)
```

Checked per image: (1) sha256 of the reconstructed payload (which embeds the exact image digest, e.g. api `sha256:6244ca29…e508ea`) equals the Rekor entry's data hash — ties log entry to image bytes; (2) the ECDSA signature in the entry verifies over that payload with the certificate's public key (`openssl dgst -verify`: Verified OK); (3) certificate SAN = the release workflow at `refs/tags/v0.2.0-alpha`, issuer extension = `token.actions.githubusercontent.com`, cert issued by `sigstore.dev/sigstore-intermediate` inside the release run's time window. Not checked here (needs registry or full cosign chain roots offline): the registry-attached signature envelope itself — that is exactly what the green `--upgrade` re-run proves once packages are public.

### Deliverable 4 — docs + cross-links

`docs/updating.md` (agency voice: what an update is, no-phone-home, the two commands, step-by-step, going back with the forward-only-migrations honesty, security-update trigger = the weekly scan, no auto-updater by design). Cross-links landed: root `README.md` (Quickstart), `install/README.md` (existing-install bullet — the stale "future --upgrade" promise replaced — + "Keep Headway up to date" bullet), `docs/network-access.md` (access answer survives updates), `deploy/compose/README.md` (`HEADWAY_IMAGE_TAG` section), `docs/supply-chain.md` ("How updates flow" + the finding-1 entry in Verification status). Stale in-script promise in `refuse_existing_install` also replaced with the real commands.

### YAML / syntax / gates

`yaml.safe_load` valid: `deploy/compose/compose.yaml`, `.github/dependabot.yml`, `.github/workflows/rebuild-scan.yml`, `ci.yml`, `release.yml` (dependabot.yml also added to ci.yml's yaml-validate target list). `bash -n install/install.sh` clean. License gate: N/A — this wave adds no dependency to any scanned tree (bash/yaml/markdown only). Accessibility: N/A — no UI surface changed (installer text follows the plain-language voice).

### Demo stack untouched (verified, not assumed)

Live `deploy/compose/.env` sha256 identical before/after the whole wave (`8c3722ae…6af3`); `docker ps` for project `headway` byte-identical to baseline (8 containers, same uptimes); API :8000 → 200 and vite :5173 → 200 after teardown. Disposable artifacts fully removed (no `hwdisp0022`/`driftchk` containers, volumes or networks remain); the ghcr credential written to the snap docker config during verification was removed (`docker logout ghcr.io`).

### What remains unproven until later events (honest pendings)

1. **The green `--upgrade` transcript** — blocked solely by finding 1. Once the five packages are public, re-run on a disposable project: recreate `deploy/compose-disposable-0022/` per this evidence (compose.yaml copy + port-reset override + `.env` with `HEADWAY_IMAGE_TAG=v0.2.0-alpha`, `HEADWAY_NETWORK=hwdisp0022`), bring it up, then `HEADWAY_COMPOSE_DIR=… HEADWAY_COMPOSE_PROJECT=hwdisp0022 ./install/install.sh --upgrade v0.2.0-alpha` — same tag twice is the honest test (mechanics: verify → pull-by-verified-digest → swap → web rebuild → up → idempotent migrate → health-gate → rollback print), and this evidence section should then gain that transcript. Also then possible: `cosign verify` / `verify-attestation` per `docs/supply-chain.md` from any laptop.
2. **Dependabot's first PRs** — config validity is yaml-proven; GitHub's acceptance of the multi-directory `directories:`+`groups` combination, and grouping behavior across the six pip directories, is provable only by the first weekly run after this lands on the default branch.
3. **rebuild-scan's first scheduled firing** — see Deliverable 2; a `workflow_dispatch` dry-run after merge exercises everything except the cron itself (and will stay red on ghcr pulls until finding 1 is fixed).
4. **`--upgrade` against a genuinely different tag** — no second five-image release exists yet; first real chance is the next release (v0.2.x/v0.3.0), which also first exercises rollback-to-previous across truly different images.
5. Migration idempotency inside the upgrade path reuses the installer's existing `run_migrations` (idempotent by design, previously live-proven in installs); its execution via the upgrade path specifically is part of pending 1.
