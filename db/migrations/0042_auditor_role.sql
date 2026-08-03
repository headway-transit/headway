-- 0042: the `auditor` role (handoff 0046, design point 4).
--
-- WHY: an external or internal auditor needs to READ EVERYTHING Headway can
-- show — figures, receipts, lineage, raw records, DQ findings, certifications
-- and the audit trail itself — and to CHANGE NOTHING. Today the only way to
-- give someone that reach is to hand them a role that can also resolve,
-- classify, or certify. That is exactly the separation-of-duties failure an
-- FTA triennial review looks for.
--
-- MODELLED ON ITS OWN AXIS, NOT AS A RUNG.
-- The four existing roles form an escalating ladder in
-- services/api/headway_api/authz.py:
--
--     viewer(0) < data_steward(1) < report_preparer(2) < certifying_official(3)
--
-- Every write gate in the API is `rank(caller) >= rank(required)`. If
-- `auditor` were given a rung, it would INHERIT every write permission at or
-- below that rung by arithmetic — put it above certifying_official and it can
-- certify; put it at data_steward and it can resolve DQ issues. There is no
-- rung that means "reads more than a viewer, writes less than one".
--
-- So the ladder is left EXACTLY as it was and `auditor` sits beside it:
--
--   * it is NOT in ROLE_RANK, so it can never satisfy a rank comparison —
--     an off-ladder role fails `require_at_least` by construction
--     (deny-by-default, not by an if-statement someone could forget);
--   * it is denied every state-changing HTTP method at the single
--     authentication choke point (auth.get_current_identity), so a future
--     endpoint added by a future wave is safe without that wave knowing
--     this role exists;
--   * for CONTENT SENSITIVITY it reads at VIEWER breadth, deliberately.
--     Migration 0028 withholds demand-response rider coordinates from the
--     read-only analyst role because a paratransit pickup point is a rider's
--     home address and an ADA trip record discloses disability status by
--     existing. That withholding is NOT waived for an auditor. Rider privacy
--     is not an auditor exception; an auditor who needs a specific rider
--     record asks for it through the same authorized path everyone else does.
--
-- The database's part is small and is exactly this: admit the role name, so
-- an account can hold it. The behaviour above lives in the API and is pinned
-- by test (services/api/tests/test_auditor_role.py).
--
-- The IdP MAY grant this role (unlike certifying_official — see 0043): an
-- auditor grant creates no ability to change anything, so federating it costs
-- nothing and offboarding an auditor in the agency directory should offboard
-- them here too.

ALTER TABLE auth.users DROP CONSTRAINT users_role_check;

ALTER TABLE auth.users
    ADD CONSTRAINT users_role_check
    CHECK (role IN ('viewer', 'data_steward', 'report_preparer',
                    'certifying_official', 'auditor'));

COMMENT ON COLUMN auth.users.role IS
    'One of viewer, data_steward, report_preparer, certifying_official '
    '(an escalating ladder) or auditor (its own axis: reads at viewer '
    'breadth, writes nothing at all). See migration 0042.';
