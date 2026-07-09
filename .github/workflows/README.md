# Headway CI workflows

One workflow (`ci.yml`) with path-filtered jobs. Only first-party actions are
used (`actions/checkout`, `actions/setup-go`, `actions/setup-python`,
`actions/setup-node`), pinned by major version — no proprietary or third-party
build steps, so the pipeline runs unchanged on a self-hosted runner
(DEVOPS_ENGINEER guardrail: open, self-hostable CI).

## Jobs

**changes** — computes which top-level areas a push/PR touched by diffing
against the PR base (or the previous push head) with plain `git diff`, and
exposes `go` / `python` / `web` booleans to the other jobs. Job-level `paths:`
filters do not exist in Actions and third-party filter actions are avoided by
policy, so this is done first-party. Any ambiguity (forced push, new branch,
missing base commit) falls back to "run everything" — path filtering may only
ever skip work it can prove is unaffected, never silently.

**go-ingestion** — builds, vets, and tests the Go ingestion service:
`go build ./... && go vet ./... && go test ./... -count=1` in
`services/ingestion`, with the toolchain pinned from `go.mod`
(`go-version-file`) and module caching keyed on `go.sum`.

**python-services** — a `[calc, transform, api]` matrix on Python 3.12. Each
service installs editable with its own `[test]` extra (calc: pytest +
hypothesis; transform: pytest; api: pytest + httpx — as declared in each
`pyproject.toml`) and runs `pytest` from the service directory, honoring the
per-service `[tool.pytest.ini_options]`.

**db-static** — runs `db/test_migrations_static.py`, the stdlib-only static
checks of the migration SQL against the canonical schema contract. It needs
only `pytest` — no live database and no psycopg — so it is a separate,
seconds-fast job rather than a matrix entry.

**web** — Node 20: `npm ci`, `npm run lint`, `npm run build`,
`npm test -- --run` in `web/`. Every step is guarded on `web/package.json`
existing (checked in a post-checkout step, because `hashFiles()` in a
job-level `if` evaluates before checkout), so the workflow stays green-able
while the frontend increment is still landing; once `web/` exists the guard is
a no-op.

**license-gate** — the machine-enforced ADR-0001 Amendment 1 policy. Installs
`go-licenses`, installs the Python services with *all* extras (so the full
declared tree is judged), runs `npm ci` if `web/` exists, then runs
`python3 scripts/license_gate.py --ecosystem all`. Tiers: permissive passes;
weak-copyleft (LGPL/MPL-2.0/EPL-class) passes only via a reviewed entry in
`scripts/license_allowlist.toml`; strong copyleft (GPL/AGPL), non-OSI (BSL,
SSPL, Confluent Community License), and *unknown* licenses fail the build.
This job is intentionally not path-filtered: the license policy gates every
merge, not just dependency bumps.

**yaml-validate** — parses `deploy/compose/compose.yaml`,
`deploy/compose/prometheus/prometheus.yml`, and every file in
`.github/workflows/` with `yaml.safe_load_all`, failing on unparseable or
missing files (including a self-check of `ci.yml`).

## Verification status (honest)

These workflows are **authored and YAML-validated but have not been executed**:
this environment has no GitHub Actions runner (and no Docker), so no live
Actions run output exists yet. What *has* been verified locally:

- `scripts/license_gate.py` ran for real against all three ecosystems
  (Go via `go-licenses csv` **and** via its no-go-licenses fallback; Python
  against the installed venv resolving the services' pyprojects; Node against
  `web/node_modules`). Output is captured in the increment's completion
  report. Known state: Go and Python pass; **Node currently fails loudly on
  `mdn-data` (CC0-1.0, a non-OSI license, dev-only transitive of
  jsdom → css-tree)** — deliberately not allowlisted, because the allowlist
  may only rescue weak-copyleft, and reclassifying CC0 is an ADR-level call.
- `ci.yml` parses (`yaml.safe_load`) and the yaml-validate job's exact script
  was executed locally against the real files (all green).
- The first real Actions run should be watched end-to-end before trusting the
  path-filter outputs.

## Not yet wired (future increments)

SBOM generation (Syft), vulnerability scanning (Grype/Trivy), image builds and
Cosign signing land with the release pipeline increment; the ADR-0005
Compose/Helm parity gate is sketched in `scripts/parity_gate.md`.
