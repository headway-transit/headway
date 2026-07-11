-- 0016: dq.issues.resolution_minutes — optional resolution effort.
--
-- How many human minutes the fix took, recorded at resolve time via
-- POST /dq/issues/{id}/resolve. NULLABLE by design: recording effort is
-- optional, and every already-resolved issue has no measurement — a missing
-- figure stays missing, never invented. The CHECK refuses negative effort
-- (NULL passes the CHECK, per SQL semantics). No default: an unmeasured
-- resolution must read as NULL, not as zero minutes.

ALTER TABLE dq.issues
    ADD COLUMN resolution_minutes INTEGER CHECK (resolution_minutes >= 0);
