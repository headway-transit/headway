# Supply-chain security: SBOMs, scanning, signing

How Headway release artifacts are inventoried (SBOM), gated (vulnerability
scan), and made verifiable (signature + attestation). Pipeline machinery is
owned by the DevOps role; thresholds and signing **policy** are owned by the
Security role (see `.claude/roles/SECURITY_ENGINEER.md`) — DevOps enforces
them, it does not set them. Everything below runs on open-source tooling
(Syft, Grype, Cosign/Sigstore — all Apache-2.0) with no proprietary service
on the critical path (ADR-0001).

## What is generated

| Artifact | Formats | Producer |
|---|---|---|
| Source-tree SBOM (full monorepo dependency inventory) | CycloneDX 1.x JSON + SPDX 2.x JSON | Syft (`anchore/sbom-action`) |
| Image SBOM, one per released container image (see table below) | CycloneDX 1.x JSON + SPDX 2.x JSON | Syft (`anchore/sbom-action`) |
| Vulnerability report, source + one per image | Grype table output in job logs | Grype (`anchore/scan-action`) |
| Image signature + CycloneDX SBOM attestation, per image | Sigstore (keyless, GitHub OIDC) | Cosign |

### Released images

Every image goes through the identical matrix leg in `release.yml`:
build → Syft image SBOM (both formats) → Grype gate (≥ high) → push →
Cosign keyless sign + CycloneDX attestation.

| Image (`ghcr.io/headway-transit/…`) | Source | Dockerfile / build context | Runs as |
|---|---|---|---|
| `headway-ingestion` | `services/ingestion` (Go connectors) | `services/ingestion/Dockerfile`, context `services/ingestion` | distroless nonroot |
| `headway-api` | `services/api` (FastAPI backend, `[ingest]` extra) | `services/api/Dockerfile`, context `services/api` | nonroot (uid 65532) |
| `headway-transform` | `services/transform` (`[kafka,db,s3]` extras) | `services/transform/Dockerfile`, context **repo root** (bakes in `contracts/raw-record-envelope.v0.schema.json`) | nonroot (uid 65532) |
| `headway-ai` | `services/ai` (`[persist]` extra) — one-shot anomaly-runner **job** image | `services/ai/Dockerfile`, context `services/ai` | nonroot (uid 65532) |
| `headway-web` | `web/` (Vite build → static nginx; `VITE_API_BASE_URL` baked at build time, default same-origin) | `web/Dockerfile`, context `web` | nginx user, port 8080 |

## Where it lands

- **Every push / PR** (`.github/workflows/ci.yml`, job `sbom-scan`):
  source-tree CycloneDX SBOM uploaded as a CI artifact
  (`sbom-source-<sha>`, 7-day retention) + Grype scan.
- **Every release tag `v*.*.*`** (`.github/workflows/release.yml`):
  source + all image SBOMs (both formats) attached as **GitHub release
  assets**; the five images in the table above pushed to
  `ghcr.io/headway-transit/headway-<service>`, each Cosign-signed by digest,
  with its CycloneDX image SBOM attached as an in-registry **attestation**.
- **Locally**: `scripts/sbom_local.sh` reproduces the source SBOM + scan via
  the official `anchore/syft` / `anchore/grype` container images (no local
  install needed); outputs to `dist/sbom/` (gitignored).

## How to verify a release

Keyless signing means there is no public key to distribute: trust is anchored
in the Sigstore transparency log and the GitHub OIDC identity of the release
workflow. With cosign >= 2.x:

```sh
IMG=ghcr.io/headway-transit/headway-ingestion:v1.2.3   # or @sha256:<digest>

# 1. Signature: must be signed by THIS repo's release workflow, from a tag.
cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp \
    '^https://github.com/headway-transit/headway/\.github/workflows/release\.yml@refs/tags/v.*$' \
  "$IMG"

# 2. SBOM attestation: recover the attested CycloneDX SBOM.
cosign verify-attestation \
  --type cyclonedx \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp \
    '^https://github.com/headway-transit/headway/\.github/workflows/release\.yml@refs/tags/v.*$' \
  "$IMG"
```

Expected identity: `https://github.com/headway-transit/headway/.github/workflows/release.yml@refs/tags/v<version>`;
expected issuer: `https://token.actions.githubusercontent.com`. Anything else
— another repo, a branch ref, another workflow file — is a verification
failure. The release pipeline runs `cosign verify` on itself immediately
after signing, so a release with an unverifiable signature never publishes.

## Scan thresholds (Security-role policy)

| Gate | Threshold | Rationale |
|---|---|---|
| CI pushes / PRs (`ci.yml` `sbom-scan`) | fail on **critical** | Keeps merges honest without blocking daily work on high-severity CVEs deep in the tree that often have no released fix yet. |
| Release tags (`release.yml`) | fail on **high** | A release is what an agency deploys; it is held to the stricter bar, and the scan runs *before* the registry push, so a red gate publishes nothing. |

Thresholds are **owned by the Security Engineer role**, recorded here and (as
they mature) in `security/control-mapping/`. Adjusting a threshold, or adding
a documented exception for a specific finding, is a Security-role decision —
never a pipeline-side tweak to make a build pass (see the "never ship a
release past a red gate" guardrail).

## Verification status (honest)

- **Verified locally (2026-07-09):** both workflow files parse as valid YAML
  (pyyaml); `scripts/sbom_local.sh` executed end-to-end against this source
  tree using the real `anchore/syft` / `anchore/grype` container images —
  SBOMs produced in both formats and Grype scan completed (see the increment
  report for real component/vulnerability counts).
- **Pending first tag push:** actual execution of `release.yml` — the ghcr
  push, Cosign keyless signing/attestation, and release-asset upload require
  a GitHub Actions runner and OIDC; none exist in the authoring environment.
  These are unverified until the first `v*.*.*` tag runs the pipeline, and
  must be treated as such.
- **Verified locally (2026-07-11):** the four new Dockerfiles
  (`headway-api`, `headway-transform`, `headway-ai`, `headway-web`) each
  `docker build` to completion in this environment; `release.yml` and
  `deploy/compose/compose.yaml` re-validated with pyyaml after the matrix /
  app-service extension. The images were **built, not run** — runtime
  behavior in compose is pending the next live `--profile app up`.
- **Pending:** image-SBOM path (Syft against a *built* image) in CI — no
  image has been release-built by the pipeline yet; only local builds and
  the source-tree SBOM path have been exercised. The ingestion image remains
  unbuilt in this environment (Go toolchain image pull not attempted here).

## How updates flow (handoff 0022)

Three pieces, each honest about what it is:

- **Dependency updates in (Dependabot, `.github/dependabot.yml`):** grouped
  weekly PRs across `go.mod` / `pyproject` / `package.json` / Dockerfile
  base images / Actions pins, labeled `dependencies`, **no auto-merge** —
  every bump rides the full CI (suites, license gate, drift gates,
  SBOM + Grype) and gets human review. *Why Dependabot and not Renovate:*
  the CI policy is first-party/self-hostable only; Renovate's zero-infra
  form is the Mend-hosted third-party app with repo write access (exactly
  what the policy refuses), and self-hosting it means new always-on
  infrastructure for grouping features v0 does not need. Dependabot sits
  inside the GitHub trust boundary the project already stands on. Stated
  honestly: Dependabot is first-party but **not** self-hostable — if the
  project ever leaves GitHub, this is the component to replace (self-hosted
  Renovate is the natural successor). Full reasoning in the config header.
- **Published-image aging alarm (`.github/workflows/rebuild-scan.yml`):**
  weekly Grype scan of the five *published* release images under the same
  `.grype.yaml` policy as the release gate. A release is scanned once at
  release time and then ages; this workflow is what notices when a fixable
  high+ CVE lands against a shipped image — it fails loudly and opens (or
  updates) an alarm issue. Remediation is a patch release: the rebuild
  pulls fixed base layers and re-passes the whole release gate. (The
  workflow header records a deliberate deviation from handoff 0022's
  "rebuild then scan" wording, with reasoning: scanning a fresh rebuild
  under-detects, because rebuilds pick up patched base layers and can scan
  clean while the published artifact stays vulnerable.)
- **Updates out to agencies (`install/install.sh --upgrade`):** agencies
  replace signed images atomically — cosign-verified against this
  document's identity *before* anything switches, pulled by verified
  digest, migrations applied by the idempotent runner, health-gated, with
  the previous tag recorded for rollback. Plain-language story:
  [`docs/updating.md`](updating.md). No phone-home: the release-list query
  happens only when an admin runs `--check-updates`/`--upgrade`.

- **Found 2026-07-20 (handoff 0022 verification), OPEN:** the five ghcr
  packages are **private** — anonymous pulls get 401 and `cosign verify`
  cannot even fetch the signatures without a `read:packages` token. Until
  a maintainer flips each package public (GitHub package settings →
  Danger Zone → Change visibility; not automatable via the REST API), no
  agency can pull a release image and `--upgrade` refuses (honestly) at
  the verification step. The signatures themselves were verified against
  the public Rekor transparency log instead — evidence in handoff 0022.

## Scan policy: fixable findings gate; "won't fix" distro findings do not

As of 2026-07-12 (`.grype.yaml`): the release gate fails on fixable vulnerabilities of high severity or above. Findings the upstream distribution has explicitly marked won't-fix (common in Debian-based Python images: libc, perl-base, ncurses) cannot be remediated by us or by any image consumer; they are excluded from the gate but remain fully visible in every release's published SBOM. The long-term remediation is distroless runtime bases (the ingestion image already uses one and passes untouched) — tracked in ROADMAP.md.

Additionally pinned (2026-07-12, individually with rationale in `.grype.yaml`): three CPython interpreter CVEs with no released fix (two have no fix version at all; one is fixed only in unreleased Python 3.15.0). Each pin names its CVE so it resurfaces for review rather than hiding in a class-wide waiver; all remain visible in published SBOMs.
