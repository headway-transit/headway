#!/usr/bin/env bash
# sbom_local.sh — produce the same source-tree SBOM + vulnerability scan the
# CI/release pipelines produce (ci.yml `sbom-scan`, release.yml), locally,
# WITHOUT installing syft or grype: both run via their official container
# images (anchore/syft, anchore/grype — Apache-2.0, same engines the
# anchore/* GitHub actions wrap).
#
# Usage:
#   scripts/sbom_local.sh                 # scan gate at Security-role release
#                                         # threshold (severity >= high)
#   FAIL_ON=critical scripts/sbom_local.sh   # the lighter CI push/PR gate
#
# Outputs (gitignored — see .gitignore "dist/"):
#   dist/sbom/headway-source.cdx.json    CycloneDX 1.x JSON
#   dist/sbom/headway-source.spdx.json   SPDX 2.x JSON
#   dist/sbom/grype-report.txt           Grype findings (table)
#
# Docker access: if the invoking shell is not yet in the docker group (fresh
# group membership), every docker command is wrapped in `sg docker -c ...`.
# The script detects which mode works and fails loudly if neither does —
# it never silently skips the scan.
#
# Threshold policy: severity thresholds are SECURITY_ENGINEER-role policy;
# this script defaults to the release gate (high). Overriding FAIL_ON is for
# local triage only and changes no policy.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/dist/sbom"
FAIL_ON="${FAIL_ON:-high}"
SYFT_IMAGE="${SYFT_IMAGE:-anchore/syft:latest}"
GRYPE_IMAGE="${GRYPE_IMAGE:-anchore/grype:latest}"

# --- docker access: direct, or via `sg docker -c` -------------------------
run_docker() {
  # $* is a single docker command line, quoted by the caller.
  if [ "${DOCKER_MODE}" = "direct" ]; then
    bash -c "$*"
  else
    sg docker -c "$*"
  fi
}

if docker info >/dev/null 2>&1; then
  DOCKER_MODE="direct"
elif sg docker -c "docker info" >/dev/null 2>&1; then
  DOCKER_MODE="sg"
else
  echo "ERROR: docker is not reachable (tried directly and via 'sg docker -c')." >&2
  echo "Install/start Docker or fix group membership; refusing to skip the SBOM." >&2
  exit 1
fi
echo "docker access mode: ${DOCKER_MODE}"

mkdir -p "${OUT_DIR}"

# --- 1. Syft: source-tree SBOM in CycloneDX-JSON and SPDX-JSON ------------
# The repo is mounted read-only; SBOMs are written into the mounted dist/sbom.
echo "==> syft (${SYFT_IMAGE}): scanning source tree ${REPO_ROOT}"
run_docker "docker run --rm \
  -v '${REPO_ROOT}:/src:ro' \
  -v '${OUT_DIR}:/out' \
  ${SYFT_IMAGE} /src \
  -o cyclonedx-json=/out/headway-source.cdx.json \
  -o spdx-json=/out/headway-source.spdx.json"

echo "==> SBOMs written:"
ls -l "${OUT_DIR}"/headway-source.*.json

# --- 2. Grype: scan the CycloneDX SBOM, gate on FAIL_ON -------------------
# Scanning the SBOM (not re-cataloging the tree) guarantees the scan judges
# exactly the inventory the SBOM records — same pattern as CI.
echo "==> grype (${GRYPE_IMAGE}): scanning SBOM, --fail-on ${FAIL_ON}"
GRYPE_RC=0
run_docker "docker run --rm \
  -v '${OUT_DIR}:/out' \
  ${GRYPE_IMAGE} sbom:/out/headway-source.cdx.json \
  --fail-on ${FAIL_ON}" | tee "${OUT_DIR}/grype-report.txt" || GRYPE_RC=$?

if [ "${GRYPE_RC}" -ne 0 ]; then
  echo "GATE FAILED: grype found vulnerabilities at severity >= ${FAIL_ON}" >&2
  echo "Report: ${OUT_DIR}/grype-report.txt" >&2
  exit "${GRYPE_RC}"
fi

echo "OK: SBOM generated and scan gate (>= ${FAIL_ON}) passed."
echo "Outputs in ${OUT_DIR} (gitignored)."
