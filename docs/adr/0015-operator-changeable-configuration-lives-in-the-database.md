# ADR-0015: Operator-Changeable Configuration Lives in the Database, Not in `.env`

- Status: Accepted
- Date: 2026-08-03
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

On 2026-08-03 a partner agency's fleet-telematics feed had been silently refusing every
page since the previous Friday. The cause was `HEADWAY_TELEMATICS_SERVICE_DAY_TZ`: the
normalizer requires it, because a service date is a local wall date and must never be
derived from a guessed timezone, and it refuses loudly rather than guess. The refusal was
correct. The variable was documented in `services/transform/README.md` and **plumbed
nowhere** — not `compose.yaml`, not `.env.example`, not the installer. The transform
container received eleven environment variables and that was not one of them.

So an agency could buy a vendor token, scope it to least privilege, enable the connector,
land the raw records, and watch every page be refused forever, with no way to satisfy the
guard. It was found only because one WARNING line survived in a container log — and that
log is destroyed by the very update an operator runs to fix things (PR #22 now keeps a copy
first).

The immediate wiring was fixed in PR #24. The question it exposed is the one this ADR
answers, because it is about to recur for feed URLs, poll interval, agency id, and every
knob added after them: **where does configuration live, and who is allowed to change it?**

The forcing argument is the audience. This platform's operators are transit staff — the
roles file and every operator-facing document assume a reader one week into Linux with no
SQL. The partner agency's ITS manager is an expert in his data and not a systems
administrator. Asking that person to SSH into a box and edit a dotfile to set a timezone is
not a documentation problem. It is a product failure, and it is the same barrier that makes
installation hard (`docs/uat-first-install.md`).

There is also a governance argument that runs the other way from the usual instinct. A
`.env` edit over SSH records **nothing**: not who changed it, not when, not what it was
before. `app.settings` (migration 0014) already records `updated_by` and `updated_at` and
carries a plain-language `description` stating the basis of each default. For a value that
helps define what a *reported federal figure* means, "we cannot say who changed this or
when" is not an acceptable answer to an auditor.

## Decision Drivers

- **The operator is not a sysadmin.** Anything a person must change after installation has
  to be reachable without a terminal.
- **Changes to reporting inputs must be attributable.** The audit trail is this platform's
  reason to exist; configuration that shapes a figure cannot sit outside it.
- **Bootstrap has to work before the database does.** Some values are needed to reach the
  database at all, and cannot live inside it.
- **Secrets must not enter the database.** Already settled practice: the session secret and
  the Ed25519 signing key are environment-only, never persisted (`install/install.sh`,
  `services/api/headway_api/signing.py`).
- **Automation must stay possible.** A scripted fleet install cannot depend on a human
  clicking through a settings screen.
- **A guard nobody can satisfy is worse than no guard.** Whatever the mechanism, the path to
  satisfying a requirement must exist and be discoverable.

## Considered Options

1. **Keep everything in `.env`.** Simplest, twelve-factor-shaped, and what we have. Requires
   shell access for every change, records nothing, and produced the failure above.
2. **Move everything to the database.** Maximally friendly, but circular: the database
   connection string cannot live in the database, and secrets should not.
3. **Split by a stated rule, with `.env` as the automation override.** Two homes, one
   boundary, and an explicit precedence.

## Decision Outcome

**Option 3.** Configuration is classified by two questions, asked in order:

1. **Is it needed before the database is reachable?** → `.env`. This is bootstrap:
   `HEADWAY_DATABASE_URL`, `KAFKA_BROKERS`, `S3_*`.
2. **Is it a secret?** → `.env`, never the database. `HEADWAY_SESSION_SECRET`,
   `HEADWAY_SIGNING_KEY`, vendor tokens.
3. **Everything else** → `app.settings`: typed, described, audited, and editable in the
   admin UI by an authorized role.

By that rule the service-day timezone belongs in the database, and so do poll interval,
agency id, and the calc policy knobs that are already there.

**`.env` remains the automation path.** Where a setting exists in both places the
environment variable wins at startup and is recorded as the source, exactly as
`HEADWAY_ACCESS_MODE` already works for the installer's `--yes` mode. A scripted fleet
install stays possible; a human never has to use it.

### Consequences

**A setting that shapes a reported figure needs more than a form field.** The service-day
timezone is the worked example: change it and yesterday's figures covered a different
twenty-four hours than tomorrow's, with nothing on either saying so. Such settings must
state the consequence before the change is accepted, and **computed figures must carry the
value they were computed under**, so a later reader can tell. `canonical.vehicle_telematics_days`
already stores `window_start`/`window_end` as instants for exactly this reason — "the local
day is auditable after the fact." The same discipline now extends to the setting itself.

**Services must read settings at run time, not only at startup.** Transform and the
connectors already hold database credentials, so this is wiring rather than architecture.
Until a given service is converted it keeps reading its environment variable, and the
boundary is enforced for new settings first.

**This is not a licence to move secrets.** The two-question test exists to keep that line
bright: a vendor token stays in `.env` no matter how inconvenient, because the database is
readable by every role that can read the database.

**Positive:** an operator can fix their own installation. Every change to a reporting input
becomes attributable. The failure that prompted this ADR becomes impossible in the
class — a setting in `app.settings` is by construction discoverable, because the UI lists
it.

**Negative:** two homes for configuration is more surface than one, and the precedence rule
has to be honoured everywhere or it becomes a source of "why isn't my change taking
effect". The rule is stated here so that question has an answer.
