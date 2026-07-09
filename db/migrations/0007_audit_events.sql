-- 0007: audit.events — append-only audit log (public-sector security posture:
-- full audit logging; history is never rewritten).

CREATE TABLE audit.events (
    event_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    subject_kind TEXT,
    subject_id   TEXT,
    detail       JSONB NOT NULL DEFAULT '{}'
);

CREATE FUNCTION audit.reject_event_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.events is append-only: % rejected', TG_OP;
END;
$$;

CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON audit.events
    FOR EACH STATEMENT
    EXECUTE FUNCTION audit.reject_event_mutation();
