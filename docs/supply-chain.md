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
| Image SBOM, one per released container image | CycloneDX 1.x JSON + SPDX 2.x JSON | Syft (`anchore/sbom-action`) |
| Vulnerability report | Grype table output in job logs | Grype (`anchore/scan-action`) |
| Image signature + CycloneDX SBOM attestation | Sigstore (keyless, GitHub OIDC) | Cosign |

## Where it lands

- **Every push / PR** (`.github/workflows/ci.yml`, job `sbom-scan`):
  source-tree CycloneDX SBOM uploaded as a CI artifact
  (`sbom-source-<sha>`, 7-day retention) + Grype scan.
- **Every release tag `v*.*.*`** (`.github/workflows/release.yml`):
  source + image SBOMs (both formats) attached as **GitHub release assets**;
  images pushed to `ghcr.io/headway-transit/headway-ingestion` (matrix-ready
  for future services), Cosign-signed by digest, with the CycloneDX image
  SBOM attached as an in-registry **attestation**.
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
- **Pending:** image-SBOM path (Syft against a *built* image) — the ingestion
  image had not been release-built in this environment; only the source-tree
  path was exercised locally.
