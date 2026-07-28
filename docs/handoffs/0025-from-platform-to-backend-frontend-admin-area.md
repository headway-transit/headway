# Handoff: platform → backend+frontend — The Admin area (first-UAT feedback wave)

## Context
First real UAT (2026-07-28, partner agency ITS manager — an expert in the data, first
time ever in Linux): "Why isn't there an admin page where you can add and connect your
data sources, manage users, connect to SSO?" And: he uploaded a logo, wants to replace
it with a better one, and "isn't given an option to do so." He is right on every count.
Today: user management exists ONLY as the installer's one-time admin creation (no API,
no UI); data-source connection lives in `.env` + docs with no in-app surface; branding
re-upload exists in the API but something blocks the replace experience in practice
(note: "logo cache-busting" is a standing queue item since wave 15 — likely the bug);
SSO is chartered (ADR-0011: native OIDC relying party — Entra ID/Google/Okta — plus
local accounts) but unbuilt. This wave builds the admin area v0 and fixes the logo.

## Design (binding)

1. **Users API + migration 0032.** `auth.users` gains `is_active BOOLEAN NOT NULL
   DEFAULT true`; login refuses deactivated accounts (same generic 401 — no
   user-enumeration oracle). Endpoints, all `certifying_official`-only, all audited
   (append-only trail, action names in the existing style):
   - `GET /users` — username, role, is_active, created; no hashes, ever.
   - `POST /users` — username (existing validation rules), role (the four session
     roles only), password (installer rules: ≥8 chars, ≤72 bytes, bcrypt via the
     existing auth helper).
   - `POST /users/{username}/reset-password` — admin sets a new password.
   - `POST /users/{username}/deactivate` + `/reactivate`.
   - **Lockout fail-safe:** refuse (409, plain language) deactivating or demoting the
     LAST active certifying_official — an agency must never be able to lock itself out
     from the UI. Pin by test.
   - Role changes: `POST /users/{username}/role` with the same last-admin guard.
2. **Data sources status API.** `GET /sources/status` (certifying_official +
   data_steward): read-only v0, derived from what the database has actually SEEN —
   per source/connector: latest raw record time, record counts (bounded window),
   parse/quarantine counts, plus the canonical freshness the ops endpoints already
   compute. No pretend "add source" mutation — connecting sources is `.env` +
   connectors today (docs/connecting-your-data.md), and the UI must say so honestly
   rather than fake a form. In-app source *configuration* is the recorded roadmap
   increment (requires settings-driven ingestion — Platform Architect open question in
   the handoff response).
3. **Logo replace — diagnose then fix.** Reproduce the "can't change it" experience:
   check whether the upload form hides once a logo exists, and whether the served logo
   URL is cache-busted after replacement (suspected wave-15 queue item). Fix so that
   uploading a new logo visibly replaces the old one immediately (version/hash query
   param or ETag semantics — record the choice), and add `DELETE /branding/logo`
   (certifying_official, audited) so "remove it entirely" exists. UI: the replace and
   remove affordances must be visible when a logo exists.
4. **`/admin` — the hub (frontend).** Nav entry visible to certifying_official only
   (server remains the enforcement; the UI is presentation). Cards/tabs:
   - **Users** — list + create + reset password + role + deactivate/reactivate, with
     the lockout fail-safe's server message surfaced verbatim at the disabled control
     (aria-disabled + reason pattern, house rule).
   - **Data sources** — the status endpoint rendered honestly (what's flowing, how
     fresh, what was refused), plus a teaching panel: how connecting works today
     (feeds in `.env`, the APC drop folder, machine keys) linking the guide. No fake
     add-source form.
   - **Branding** — the existing BrandingView reached from here (move or link; keep
     its route working), with the logo fix live.
   - **Settings** — the calc knobs already served by GET/PUT `/settings` (migration
     0014; runner reads them) finally get their UI room: list each knob with its
     current value, basis citation, and edit affordance under the API's existing
     authz. The sandbox's "change it in Settings" language must now be true.
   - **Single sign-on** — an honest card, no toggles: SSO via native OIDC (Entra ID,
     Google, Okta) is designed (ADR-0011) and not yet available; local accounts are
     today's story; the card cites the ADR by number. Nothing pretends.
5. **Honest scope:** no OIDC implementation this wave; no in-app source mutation; no
   machine-keys UI beyond a link to the existing docs section if no view exists (do
   NOT build a new keys UI this wave — record as follow-up); no email; password resets
   are admin-performed (self-service reset needs email infrastructure — record).

## Outputs
API tests incl. full authz matrix + lockout fail-safe + deactivated-login refusal;
migration 0032 applied live; openapi.json regenerated; web tests + axe + contrast
green; build clean; live click-throughs (admin as certifier: create a user, sign in as
that user in a second session, reset their password, deactivate, verify refused login,
reactivate; replace the logo twice and SEE the change; edit one settings knob and show
the sandbox/runner path reflects it); evidence appended here. No commits — the
orchestrator integrates and commits.

## Open Questions
- In-app data-source configuration (settings-driven ingestion) — Platform Architect.
- OIDC implementation increment (ADR-0011) — now has its first real requester.
- Self-service password reset (needs mail); machine-keys management UI.

## Outputs — evidence

### Response — backend+frontend engineer (2026-07-28, working tree on `ba25f1e`)

Contract accepted; all five design points built, plus the coordinator's
optional Updates card. Everything below verified against the live vite dev
server (`localhost:5173`), the live API (`127.0.0.1:8000`, restarted once —
ops notes below), the live compose TimescaleDB (migration 0032 applied) and
the live compose MinIO (the logo flow, end to end). No commits — tree left
for the orchestrator.

**What shipped**

Backend (`services/api/` + `db/migrations/0032_users_admin.sql`):

1. **Migration 0032** — `auth.users.is_active BOOLEAN NOT NULL DEFAULT
   true`, backfilled from `NOT disabled`; `disabled` becomes a **read-only
   GENERATED column** (`NOT is_active`) instead of being dropped, because
   the agency updater (`install.sh --update-from-source`) runs migrations
   BEFORE the service rebuild and the pre-0032 login path SELECTs
   `disabled` — old code keeps working through the update window, and drift
   between the two flags is structurally impossible (a write to the
   generated column errors). Dropping the compatibility column is a later
   migration once no supported version reads it.
2. **Users API v0** (`routers/users.py`): `GET /users`, `POST /users`,
   `POST /users/{u}/reset-password`, `/deactivate`, `/reactivate`,
   `/role` — all certifying_official-only, all audited in the same
   transaction as the change (`user_created`, `user_password_reset`,
   `user_deactivated`, `user_reactivated`, `user_role_changed`).
   Validation is the INSTALLER's rules verbatim (username charset;
   password ≥ 8 chars, ≤ 72 bytes via the loud bcrypt refusal — never
   truncation). No endpoint ever serves password material — the field
   does not exist in any response model. **Lockout fail-safe**: deactivating
   or demoting the last ACTIVE certifying official is a plain-language 409;
   pinned by four tests (deactivate, demote, inactive-admin-doesn't-count,
   second-active-admin-unlocks). Deactivate/role responses carry a
   plain-language note that an existing session lives on for up to the
   token TTL (sessions are stateless JWTs; per-request revocation is a
   recorded follow-up below).
3. **Deactivated login = the same generic 401.** `auth.py` now reads
   `is_active` and refuses a deactivated account with the *byte-identical*
   message as a wrong password (no user-enumeration oracle; was previously
   a 403 naming the account state). The audit trail keeps the real reason
   (`login_denied`, `{"reason": "account deactivated"}`).
4. **`GET /sources/status`** (`routers/sources.py`, data_steward and
   above): read-only, derived from what raw.records has actually SEEN per
   (source, connector) — latest landed/fetched times, first-seen, all-time
   and bounded-window (`window_hours`, default 24, max 720) record counts,
   malformed (parse-quarantined) counts, per-row `simulated` flag — plus
   the canonical vehicle-position liveness (`SELECT now(), max(time)`, the
   exact ops-endpoint freshness) and a served `connecting_note` stating
   how connecting REALLY works (`.env` feeds, APC drop folder, machine-key
   API, `docs/connecting-your-data.md`). **No add-source mutation exists**,
   and a test pins that `POST /sources*` stays 404/405.
5. **Logo replace fixed + `DELETE /branding/logo`** — details under the
   root-cause heading below.

Frontend (`web/`):

6. **`/admin` hub** (`AdminView.tsx`), nav entry "Admin" for the
   certifying official only (UX; the API enforces roles on every call —
   the old "Branding" nav entry moved into the hub, `/settings/branding`
   route unchanged). Cards: Users, Data sources, Branding (link),
   Settings, plus two HONEST cards with zero interactive controls —
   **Single sign-on** ("Designed, not yet available (ADR-0011)"; Entra
   ID/Google/Okta via native OIDC named; local accounts are today's
   story) and **Updates** (updating happens on the server by an
   administrator; both commands verbatim —
   `./install/install.sh --update-from-source` and
   `./install/install.sh --check-updates` / `--upgrade` — and the stated
   reason there is no update button: a web session must never be able to
   replace the software it runs in).
7. **`/admin/users`** (`AdminUsersView.tsx`): list (username/role/status/
   created — never any password material), create, reset password, change
   role, deactivate/reactivate. The lockout fail-safe is stated AT the
   control (aria-disabled + visible reason, aria-describedby — never a
   native `disabled` that swallows the click), and a click still asks the
   server, whose 409 renders VERBATIM at the control. Server notes
   (session-lifetime honesty) render verbatim beside confirmations. The
   list is re-read from the server after every change, never
   client-adjusted.
8. **`/admin/sources`** (`AdminSourcesView.tsx`): the status payload
   rendered honestly — counts verbatim, refused-rows columns with the
   quarantine explanation, SIMULATED badges (text + icon, the house
   component), the server's `connecting_note` verbatim, the canonical
   liveness panel, and the teaching panel ("How connecting works today":
   .env feeds / APC drop folder / vendor adapters + machine keys /
   `docs/connecting-your-data.md`). **No add-source form** — pinned by
   test. Opens for data stewards too (`canViewSourceStatus`), matching
   the API rule.
9. **`/admin/settings`** (`AdminSettingsView.tsx`): every non-branding
   knob GET /settings serves — current value VERBATIM in the edit field
   (strings end to end), the served description as the basis citation,
   who/when last changed, save via PUT /settings/{key} (server refusals
   verbatim), branding keys explicitly stated as living in the Branding
   room. `SandboxView` now links here beside its apply-note ("Open
   Settings (Admin) to make an audited change.") — the sandbox's
   "change it in Settings" language is finally true.
10. **Branding logo section rebuilt** (`BrandingView.tsx`): with a logo
    present, the CURRENT logo is displayed and the section offers an
    explicit **"Replace logo"** file field + save button and a **"Remove
    logo"** button; with none, the original upload flow. After any
    change the page re-reads GET /branding and pushes it to the shell
    store, so the header and preview update immediately.

**Logo bug — root cause found (design point 3)**

Reproduction case, the UAT quote via the project lead: *"on the Branding
page, Save affordances exist for the primary and accent colors, but there
is NO way to tell it to replace and save the LOGO once one exists."*

Two co-conspiring causes, confirmed in code and live:

- **Affordance**: with a logo uploaded, the section's only controls were a
  file input labeled "Logo file" and a button labeled "Upload logo" under
  the line "A logo is uploaded" — nothing named *replace*, nothing offered
  *remove*, and the current logo was not even shown in the section. To a
  non-Linux-native expert user that reads as "no option to change it."
- **Cache (the wave-15 standing queue item — confirmed)**: the logo URL
  was fixed (`/branding/logo`) and served `Cache-Control: public,
  max-age=300`. Inside the SPA the `<img src>` never changed after a
  replacement, so the browser never re-fetched at all; even on reload the
  old bytes were served for up to five minutes. So even when the manager
  DID successfully re-upload, **the old logo stayed on screen** — "it
  doesn't let me replace it" was the truthful reading of what he saw.

**Recorded choice**: version query param + ETag semantics. `GET /branding`
serves `logo_version` (epoch-µs of the audited `brand_logo_meta` row's
`updated_at`, which every upload advances); the shell renders
`/branding/logo?v=<logo_version>`, so a replacement mints a new URL and is
visible immediately; the logo response carries `ETag: "<version>"` and
honors `If-None-Match` with 304. `DELETE /branding/logo` added
(certifying_official, audited `branding_logo_removed`, object deleted from
the store before the meta+audit transaction — idempotent, and a meta row
pointing at deleted bytes already serves the plain-language 404).

**Migration status (live)**

```
$ python3 db/migrate.py         (PG* env, live compose TimescaleDB)
applying 0032_users_admin.sql ... ok
applied 1 migration(s)
$ python3 db/migrate.py         (re-run)
up to date: 32 migration(s) already applied
```
Schema verified live: `is_active boolean NOT NULL` (writable),
`disabled boolean GENERATED ALWAYS` — the pre-0032 login SELECT
(`... role, disabled FROM auth.users WHERE username=...`) still answers
correctly, and `UPDATE auth.users SET disabled = true` is refused by
PostgreSQL (`GeneratedAlways column "disabled" can only be updated to
DEFAULT`) — the no-drift property is enforced by the database itself.
`db/test_migrations_static.py`: 29 pass.

**Gates (all green, run 2026-07-28)**

```
services/api:  pytest tests -q                → 371 passed
               (new: test_users.py 24, test_sources_status.py 10,
                test_branding.py +8 logo-version/ETag/DELETE tests,
                test_auth.py deactivated-login rewritten to pin the
                generic-401 byte-equality; conftest FakeConn extended:
                users-admin SQL, raw.records aggregate, store.delete)
               openapi.json regenerated       → 60 paths (was 54; +6:
               /sources/status, /users, /users/{username}/{deactivate,
               reactivate,reset-password,role}; /branding/logo gains
               DELETE; /branding gains logo_version)
web:           npx vitest run                 → 35 files, 243 tests, all pass
               (was 34/223 — +18 admin.test.tsx, +3 branding.test.tsx
                incl. the UAT-reproduction test, upload test updated to
                the refetch contract)
               npm run lint                   → oxlint, no findings
               npm run check:contrast         → 87/87 PASS (no new color
               pairs — admin UI uses existing AA-verified tokens only)
               npm run build                  → tsc -b && vite build, clean
               (index 641.59 kB │ gzip 178.54 kB; MapView chunk unchanged)
```
Axe is asserted in the new tests (hub, users incl. the aria-disabled
lockout state, sources, settings, branding replace state) via the house
`expectNoAxeViolations` gate.

**Live click-through** (headless system Chrome 149 via playwright-core,
real logins, live API + DB + MinIO; screenshots + full transcript in
`docs/images/handoff-0025/`, log `clickthrough-log.txt`):

- **Admin hub (certifier)**: cards render; SSO card status "Designed, not
  yet available (ADR-0011)", `0` buttons/inputs inside; Updates card shows
  both commands verbatim, `0` buttons (`certifier-admin-hub.png`).
- **Create → second session → reset → deactivate → refused login →
  reactivate** (the full handoff sequence, all live):
  `avery.uat` created as data steward (`certifier-admin-users-created.png`)
  → signed in in a second browser context ("Signed in as avery.uat (data
  steward)", `avery-second-session-today.png`) → password reset by the
  admin → deactivated (confirmation + the server's session-lifetime note
  verbatim, `certifier-admin-users-deactivated.png`) → login with the
  correct new password refused with the GENERIC message "That username and
  password combination was not recognized." (`avery-login-refused-
  deactivated.png`) — byte-identical to the wrong-password refusal, also
  proven at the API level side by side — → reactivated → signed in again
  with the reset password. Audit rows verified by SQL for every step
  (`user_created` 944 … `user_reactivated` 952, `login_denied` with
  `{"reason": "account deactivated"}`).
- **Lockout fail-safe live**: "Deactivate certifier" renders
  `aria-disabled="true"` with the stated reason at the control; the click
  still fires and the server's 409 renders VERBATIM beneath it
  (`certifier-admin-users-lockout.png`). The API-level checks also pin the
  demote-refusal 409.
- **Data sources (certifier + dsteward)**: 10 live (source, connector)
  rows straight from the real raw.records registry (gtfs_rt 35,105
  records; the simulated sources badged; every count matching the SQL
  aggregate), connecting note verbatim, teaching panel, and **0**
  add-source forms/inputs on the page (`certifier-admin-sources.png`,
  `dsteward-admin-sources.png`).
- **Settings knob, edited and reflected**: `gap_threshold_seconds`
  300 → 240 saved ("'gap_threshold_seconds' is now 240. The change is
  recorded in the audit trail; the next calculation run reads it.",
  `certifier-admin-settings-saved.png`; audit events 972/981/982 with
  old→new in detail); the Settings **sandbox** then shows "Today's value:
  240" for the same knob (`certifier-sandbox-reflects-240.png`) — the
  sandbox/runner read path is the same audited app.settings row the admin
  page writes. Restored to 300 (audited) afterwards.
- **Logo replaced twice and SEEN, then removed**: upload LOGO A → header
  URL `/branding/logo?v=1785260144167236` (`certifier-branding-logo-a.png`)
  → **Replace** with LOGO B → new URL `?v=1785260144399189`, header +
  section + preview visibly show B immediately
  (`certifier-branding-logo-b-replaced.png`) → **Replace** with LOGO C →
  `?v=1785260144657697`, visible immediately
  (`certifier-branding-logo-c-replaced.png`) → **Remove logo** → header
  logo gone, section back to the upload flow
  (`certifier-branding-logo-removed.png`). Audit: `branding_logo_uploaded`
  ×3, `branding_logo_removed` ×1 (events 983–986). Bytes went to the live
  MinIO (`headway-raw` bucket) — the API was restarted with the S3 env for
  this (ops notes).
- **Steward gating**: dsteward's nav has **no** Admin link; in-app
  navigation to `/admin` shows the plain not-allowed text
  (`dsteward-admin-not-allowed.png`); `/admin/sources` opens and renders
  the same 10 rows — the same rule as the API
  (`dsteward-admin-sources.png`).

**Decisions + deviations (recorded, with reasoning)**

1. **`/sources/status` role gate = `require_at_least("data_steward")`.**
   The handoff names certifying_official + data_steward; the platform's
   role model is an escalating hierarchy (authz.py), so report_preparer
   (rank above steward) also reads. Carving a non-monotonic exception
   would break the hierarchy invariant every other endpoint upholds; the
   matrix test pins viewer 403 / steward+preparer+certifier 200.
2. **Migration keeps `disabled` as a GENERATED column** instead of the
   naive drop — the update-window compatibility requirement (coordinator
   note) plus the no-two-writable-flags drift rule. Recorded above.
3. **Nav "Branding" entry replaced by "Admin"** — branding is reachable
   as a hub card; `/settings/branding` route and all its tests unchanged
   ("move or link" — this is link, with the nav slot reclaimed).
4. **Updates card included** (coordinator optional item) — scope stayed
   clean (copy + hub card + tests only). Kept generic about
   source-vs-release following, as instructed: the web app cannot and
   should not see `.env`.
5. **Client-side lockout reason is house copy, not the server string** —
   the reason shown at the aria-disabled control is written in copy.ts
   (same rule, plain words); the SERVER's message appears verbatim the
   moment the control is exercised (and in the click-through screenshot).
   Only the server message is authoritative; the test suite pins both.
6. **`ChangeRole`/`Deactivate` responses carry session-TTL honesty notes**
   rather than implying instant effect — per-request `is_active`/role
   re-checks would add a DB round-trip to every request; recorded as a
   follow-up (below) rather than smuggled in.
7. Pre-existing, noted not changed: the 403 for a non-certifier on
   admin endpoints is the shared `require_certifying_official` message
   ("…cannot certify figures…") — accurate but certification-flavored on
   user-management routes. Rewording it touches every pinned test that
   asserts it; left for a copy pass, recorded here.

**Ops notes (environment actions, none in the repo)**

- Live API restarted once to pick up this wave (it runs as host uvicorn,
  `127.0.0.1:8000`, `--factory headway_api.app:create_app`). Env used:
  `HEADWAY_DATABASE_URL` (PG key-value form), `HEADWAY_SIGNING_KEY`
  (unchanged, from deploy/compose/.env), `HEADWAY_CORS_ORIGINS=
  http://localhost:5173,http://localhost:4173` (the 0024 requirement),
  plus — NEW this wave, required for the logo flow — `S3_ENDPOINT=
  127.0.0.1:9000, S3_ACCESS_KEY/SECRET_KEY (compose MinIO root creds),
  S3_BUCKET=headway-raw, S3_USE_SSL=false`. The previous process env had
  NO S3_* vars, so logo upload would have been a 503 on the live box —
  found and fixed by this restart.
- `HEADWAY_SESSION_SECRET` was REGENERATED (openssl rand -hex 32): the
  old value lived only in the killed process's environment and is
  persisted nowhere (checked deploy/compose/.env and the repo). All
  previously issued tokens were >30 min old (expired) at restart, so no
  live session was invalidated that TTL had not already ended. Same
  precedent as handoff 0023's restart note. The API is LEFT RUNNING with
  this env.
- Live-state hygiene after the click-throughs: UAT accounts `morgan.uat`
  (API-level sequence) and `avery.uat` (browser sequence) removed by
  direct SQL DELETE (auth.users carries no immutability trigger; the
  append-only audit trail keeps every action they proved).
  `gap_threshold_seconds` restored to 300 via the audited PUT. The logo
  was removed via the new DELETE endpoint, returning the instance to its
  pre-wave `has_logo: false`. Users table now: certifier + dsteward,
  active, as before.
- The 0024 idle-pool 500 issue did NOT recur this wave (the restart gave
  a fresh pool); it remains the recorded backend follow-up.
- The guided-tour overlay ("Step 1 of 5") auto-offers on each fresh
  session and appears in some screenshots — pre-existing behavior, not
  part of this wave.

**Honest scope — not done / follow-ups (recorded)**

- **No OIDC implementation** (ADR-0011 stays designed-only; the SSO card
  says exactly that). Now has its first real requester — the open
  question stands for the Platform Architect / Security Engineer.
- **No in-app source mutation** — the recorded roadmap increment
  (settings-driven ingestion, Platform Architect open question).
- **No machine-keys management UI** — the sources teaching panel points
  at the guide's machine-keys section; a keys UI is a recorded follow-up
  (the API for it has existed since handoff 0006).
- **Password resets are admin-performed**; self-service reset needs email
  infrastructure Headway does not have — recorded.
- **Session tokens outlive deactivation/demotion by up to the TTL**
  (30 min default): stateless JWTs are not re-checked against auth.users
  per request. The API states this honestly in its responses; a
  per-request active/role check (one indexed lookup) or a token denylist
  is the recorded backend follow-up if the window is ever unacceptable.
- **In-UI update visibility beyond the honest card** (actual
  version/update-availability surfaced in the app) — the UAT user asked
  for visibility; the card teaches the mechanism but shows no live
  version data. Recorded as a follow-up for the DevOps/backend pair
  (needs a server-side "what am I running" source the web app may read).
- Manual screen-reader pass remains the standing gap noted in
  `web/README.md`; keyboard paths are exercised in the automated
  interaction tests (menus, forms, aria-disabled controls with
  aria-describedby reasons).
- `git status` shows exactly the scoped paths: modified `services/api/*`
  (8 files incl. regenerated openapi.json + tests), `web/*` (10 files),
  new `db/migrations/0032_users_admin.sql`, new `services/api` routers
  `users.py`/`sources.py` + `tests/test_users.py`/`test_sources_status.py`,
  new `web/src/views/Admin{View,UsersView,SourcesView,SettingsView}.tsx` +
  `web/src/test/admin.test.tsx`, new `docs/images/handoff-0025/`
  (15 screenshots + click-through log), and this handoff file.
  `install/`, `deploy/`, `.github/` untouched. No commits, per the
  wave's rule.
