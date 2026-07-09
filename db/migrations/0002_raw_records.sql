-- 0002: raw.records — registry of immutable raw records.
-- Payload bytes live in the object store / Kafka; this table is the index.

CREATE TABLE raw.records (
    record_id         TEXT PRIMARY KEY,  -- lowercase hex SHA-256 of raw payload bytes (matches envelope)
    source            TEXT NOT NULL,
    connector         TEXT NOT NULL,
    connector_version TEXT NOT NULL,
    content_type      TEXT NOT NULL,
    payload_encoding  TEXT NOT NULL,
    payload_ref       TEXT,              -- object key when object_ref
    fetched_at        TIMESTAMPTZ NOT NULL,
    landed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    parse_status      TEXT NOT NULL CHECK (parse_status IN ('ok', 'malformed')),
    parse_error       TEXT
);

-- Raw records are never mutated after landing (shared constraint: full
-- provenance). Any attempt to UPDATE or DELETE fails loudly.
CREATE FUNCTION raw.reject_record_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'raw.records is immutable: % rejected', TG_OP;
END;
$$;

CREATE TRIGGER records_immutable
    BEFORE UPDATE OR DELETE ON raw.records
    FOR EACH STATEMENT
    EXECUTE FUNCTION raw.reject_record_mutation();
