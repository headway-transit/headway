-- 0032: users admin v0 (handoff 0025, design point 1).
--
-- WHY: the first real agency UAT (2026-07-28, partner agency ITS manager)
-- asked the obvious question — "Why isn't there an admin page where you can
-- add and connect your data sources, manage users, connect to SSO?" Until
-- this wave, user management existed ONLY as the installer's one-time admin
-- creation. The admin Users API (services/api routers/users.py) needs an
-- explicit active flag it can flip both ways, audited.
--
-- is_active SUPERSEDES disabled (added by 0009); the handoff's binding
-- design names the column is_active. Two independently-writable flags for
-- one fact would be a drift hazard, and dropping disabled outright would
-- break OLD code briefly running against the NEW schema (the updater runs
-- migrations BEFORE the service rebuild — install.sh --update-from-source —
-- and the pre-0032 login path SELECTs disabled). So disabled becomes a
-- READ-ONLY GENERATED column over is_active: old readers keep working
-- through the update window, drift is structurally impossible (writes to a
-- generated column error loudly), and is_active is the single writable
-- source of truth from this migration on. Dropping the compatibility column
-- is a later migration, once no supported version reads it.
--
-- LOCKOUT FAIL-SAFE (enforced in the API, pinned by test): the Users API
-- refuses (409, plain language) to deactivate or demote the LAST active
-- certifying_official — an agency must never be able to lock itself out
-- from the UI. The database keeps the flag; the API keeps the guard.
--
-- Login refuses deactivated accounts with the SAME generic 401 as a wrong
-- password — account state is never an enumeration oracle (services/api
-- auth.py; the refusal is still audited with its real reason).

ALTER TABLE auth.users
    ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;

UPDATE auth.users SET is_active = NOT disabled;

ALTER TABLE auth.users DROP COLUMN disabled;

ALTER TABLE auth.users
    ADD COLUMN disabled BOOLEAN GENERATED ALWAYS AS (NOT is_active) STORED;
