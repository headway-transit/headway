# Security Policy

Headway handles transit operations data and produces figures agencies certify to federal regulators. We take reports seriously and appreciate coordinated disclosure.

## Reporting a vulnerability

- **Preferred**: GitHub's private vulnerability reporting on this repository (*Security* tab → *Report a vulnerability*). This reaches the maintainers privately.
- **Email**: support@bekus.co (mark the subject SECURITY).
- Please include: affected component/path, reproduction steps, impact assessment, and any suggested fix. **Never include real rider or agency data** in a report — synthetic reproduction data only.
- Please do **not** open public issues for suspected vulnerabilities before we've had a chance to respond.

## What to expect

Headway is a volunteer-maintained open-source project in alpha. We aim to acknowledge reports within a few business days and to keep you informed as we triage — we don't promise commercial-grade SLAs, and we'll be honest about timelines rather than inventing them. Credit is offered in release notes for responsibly disclosed issues (or anonymity, your choice).

## Scope

- **In scope**: this repository's code and released artifacts — the services (`services/`), web app (`web/`), installer (`install/`), deployment definitions (`deploy/`), CI/release pipeline, and published container images.
- **Out of scope**: individual agencies' deployments and infrastructure (report those to the agency), vulnerabilities in upstream dependencies (report upstream; we'll ship the bump), and findings requiring physical access or already-privileged accounts behaving as designed.

## Supported versions

| Version | Supported |
|---|---|
| `main` (alpha) | ✅ current fixes land here |
| tagged alphas (e.g. `v0.1.0-alpha`) | ⚠️ no backports during alpha — upgrade to `main` |

## Verifying what you run

Release images are signed (Cosign keyless) with SBOMs attached; verification commands and the expected signing identity are documented in [`docs/supply-chain.md`](docs/supply-chain.md). If a signature doesn't verify, don't run the artifact — and please report it.

## Design posture (context for researchers)

NIST SP 800-53 moderate is the design reference; secrets are runtime-injected (never committed — full-history scanned); raw data is immutable with append-only audit logging; machine credentials are hashed at rest with scope- and source-bound authority. The interesting attack surfaces are documented rather than hidden: see `docs/handoffs/0006` for the machine-API design and its explicitly recorded v0 trade-offs.
