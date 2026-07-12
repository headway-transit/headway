# Contributing to Headway

Thank you for contributing. Headway produces figures that a human certifies
to the FTA; an unexplained gap becomes a finding in a triennial review. That
stakes standard shapes every rule below. The eight non-negotiable project
constraints are in
[`.claude/roles/_SHARED_CONSTRAINTS.md`](.claude/roles/_SHARED_CONSTRAINTS.md);
read them before your first substantial change — reviewers apply them
literally.

## Development setup

Two supported paths:

**Guided installer** (single Linux box, Docker required):

```sh
./install/install.sh --check   # dry run: verifies Docker, ports, memory, disk
./install/install.sh           # full install; see install/README.md
```

**Direct Compose** (from `deploy/compose/`, see `deploy/compose/README.md`):

```sh
docker compose up -d                          # infrastructure only
docker compose --profile app up -d --build    # infrastructure + app services
```

## Running the test suites

Each service carries its own suite; run the one(s) you touched (commands are
from each service's README, which also records the last verified run):

| Area | Commands |
|---|---|
| `services/ingestion` (Go) | `go build ./... && go vet ./... && go test ./... -count=1` |
| `services/calc` | `cd services/calc && python3 -m pytest tests/ -q` |
| `services/transform` | `cd services/transform && python3 -m pytest tests/ -q` |
| `services/api` (unit) | `cd services/api && python3 -m pytest tests/ -q` |
| `services/api` (integration, real Postgres) | `python -m pip install -e "services/api[test]" -r tests/integration/requirements.txt && python -m pytest tests/integration -q` (needs `HEADWAY_IT_ADMIN_URL`; see `tests/integration/README.md`) |
| `services/ai` | `python3 -m pip install -e "services/ai[test]" && cd services/ai && python3 -m pytest tests/ -q && python3 -m headway_ai.regression` |
| `db` migrations (static) | `cd db && python3 -m pytest test_migrations_static.py -q` |
| `web` | `cd web && npm install && npm test -- --run && npm run build && npm run check:contrast` |

CI (`.github/workflows/ci.yml`) runs the same suites plus the **license gate**
(ADR-0001: OSI-approved dependencies only, tiered; allowlist in
`scripts/license_allowlist.toml`) and an SBOM + vulnerability scan. All gates
must be green to merge.

## Verification before assertion

This is project Constraint 8 and the core review norm: **no claim without
evidence**. A PR description states what was verified and how — the suites
run and their output, the queries that prove lineage rows exist, the compose
stack it was exercised against. "The code looks correct" and "tests should
pass" are not evidence and will draw a request for the actual run. New logic
ships with new tests; changes that touch data flow must show provenance is
intact (a reported value still walks back to its raw source records).

## Cross-cutting changes: ADRs and handoffs

- **Architecture-level decisions** (boundaries, contracts, dependencies with
  license implications, anything that constrains more than one service) are
  recorded as a numbered ADR in [`docs/adr/`](docs/adr/). Follow the format
  of the existing ADRs (context, drivers, options, outcome, consequences).
  Accepted ADRs are never rewritten; supersede them with a new one.
- **Work that crosses an ownership boundary** (one area handing an interface,
  schema, or policy to another) moves via an explicit handoff document in
  [`docs/handoffs/`](docs/handoffs/), named
  `NNNN-from-<role>-to-<role>-<slug>.md`, using the format defined in
  `.claude/roles/_SHARED_CONSTRAINTS.md` (Context / Inputs / Outputs / Open
  Questions / Verification Evidence). The receiver appends a `## Response`.
  Interface changes after a handoff require a new handoff, not an
  edit-in-place.
- **Substantial non-architectural proposals** go through the RFC process
  defined in [`GOVERNANCE.md`](GOVERNANCE.md).

## Changing calculation logic (`services/calc`)

Calculations produce regulatory figures, so they carry extra, non-optional
rules:

1. **Every calculation version has a row in
   [`services/calc/REGULATORY_TRACKER.md`](services/calc/REGULATORY_TRACKER.md).**
   No calc version ships without one. The row records what it implements, the
   citation as a *pointer to the published source* (never a number recited
   from memory), the verification status, and the source version verified
   against.
2. **Golden datasets are mandatory.** A new or changed calculation adds or
   updates a golden dataset under [`tests/golden/`](tests/golden/)
   (`fixture.json`, `expected.json`, and a `BASIS.md` stating exactly what
   the expected values are based on and what they are *not* — see
   `tests/golden/upt_v0/BASIS.md` for the pattern).
3. **Versions are never rewritten.** Changing calculation logic mints a new
   version and a new tracker row; shipped versions stay runnable (see the
   retained `compute_*_v0_*` entry points) and their tracker rows are never
   deleted or edited into something else.
4. **Fail loudly.** No silent drop, coalesce, or interpolation path. Gaps and
   conflicts surface as data-quality findings with an owner; a calculator
   refuses to emit a certifiable figure over an unresolved gap.

## Review rejection criteria

Reviewers reject, regardless of code quality, any change that:

- **Has AI compute a reported number.** All regulatory figures come from
  deterministic, versioned, unit-tested calculation logic. AI features
  (anomaly detection, DQ triage, narrative drafting, natural-language query)
  operate on top of computed results, must cite the source records they
  reference, and any AI output shown to a user is labeled AI-generated and
  requires human review before inclusion in any submission. A PR in which a
  model output flows — directly or by default value — into a reportable
  figure is rejected.
- Breaks provenance (a reported value no longer traces to raw records).
- Puts a proprietary or non-OSI-licensed dependency on the core critical
  path (ADR-0001; the CI license gate is the machine check).
- Works only in the cloud (on-prem Compose parity is required).
- Introduces an unauthenticated surface or puts secrets/PII in code or logs.

## License and sign-off

Headway is licensed under **Apache-2.0** (see [`LICENSE`](LICENSE) and
[`NOTICE`](NOTICE); rationale in
[`docs/adr/0001`](docs/adr/0001-core-license-apache-2-and-osi-only-dependencies.md)).
By contributing you agree your contribution is licensed under Apache-2.0.

The project uses the **Developer Certificate of Origin (DCO)** — not a CLA.
Every commit must carry a `Signed-off-by` line certifying you have the right
to submit the work under the project license (the DCO text is at
[developercertificate.org](https://developercertificate.org)):

```
Signed-off-by: Your Name <you@example.org>
```

`git commit -s` adds it for you. The name must be yours (no pseudonymous
sign-offs of work you cannot attest to). A CI sign-off check is adopted as of
this document and will be wired into `.github/workflows/ci.yml`; until then
reviewers check sign-off manually and unsigned commits are asked to be
amended. Rationale for DCO over CLA is recorded in
[`GOVERNANCE.md`](GOVERNANCE.md).

## Security issues

Do not open public issues for vulnerabilities — see
[`SECURITY.md`](SECURITY.md).

## Conduct

All project spaces are governed by
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
