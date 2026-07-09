-- 0006: dq.issues — gaps, conflicts, and validation failures surface here
-- with an owner and a resolution workflow (shared constraint: fail loudly).

CREATE TABLE dq.issues (
    issue_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_type        TEXT NOT NULL,
    severity          TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'blocking')),
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'owned', 'resolved')),
    owner             TEXT,
    title             TEXT NOT NULL,
    description       TEXT NOT NULL,
    source_record_ids TEXT[],
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    resolution        TEXT
);
