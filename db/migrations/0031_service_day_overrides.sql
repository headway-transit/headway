-- 0031: app.service_day_overrides — the agency's audited day-type calendar
-- declarations (handoff 0020; calc daytype_v0 0.1.0).
--
-- Regulatory basis (2026 NTD Policy Manual, Full Reporting, pp. 155–156 —
-- verbatim in services/calc/REGULATORY_TRACKER.md, "Verified — Days Operated
-- and day-type schedules"; never from memory):
--   p. 155: "Full Reporters must report the total number of days operated
--   for the weekday schedule, Saturday schedule, and Sunday schedule
--   service."
--   p. 156: "Transit agencies must report holiday service under the day
--   that most closely reflects the service."
-- Which schedule a holiday "most closely reflects" — and which days were
-- atypical — is an AGENCY DECLARATION. Headway records it; it never infers
-- it (canonical holds no GTFS calendar/calendar_dates; day-of-week is the
-- documented v0 fallback).
--
-- WHY A TABLE, NOT app.settings ROWS (the handoff-0020 "smallest honest
-- design" decision, documented): settings are a fixed set of SEEDED keys
-- (migration 0014 — an unknown key is a 404, never a new row), one TEXT
-- value each. Calendar declarations are per-DATE facts with their own
-- required reason and their own audit attribution, read by date range; a
-- growing set of dates cannot honestly live in one seeded TEXT value (no
-- per-date attribution, no typed validation, no range reads). A dedicated
-- table gives each declaration a validated shape, a PRIMARY KEY on the
-- date (two declarations for one date cannot coexist), and row-level
-- updated_by/updated_at — the same audited-surface rules as settings,
-- applied per date.
--
-- MUTABLE-WITH-AUDIT, not append-only (the app.settings precedent, NOT the
-- cert.attestations one — deliberate): an override is policy CONFIGURATION,
-- not evidence. Every figure computed under an override snapshots the full
-- row (date, assignment, flag, reason, updated_by, updated_at) into its
-- detail JSONB (headway_calc.daytype), so what governed a persisted figure
-- rides the figure permanently even if the declaration later changes — and
-- the API writes old + new values into audit.events on every change,
-- exactly like PUT /settings/{key}.
--
-- Analyst role note (migration 0028's FUTURE TABLES clause): app.* is
-- excluded from headway_readonly entirely, so this table is not exposed —
-- correct: declarations carry operator attribution; analysts see their
-- EFFECT in computed.metric_values.detail.
--
-- Constraints:
--   * assigned_day_type — the p. 156 holiday reassignment; NULL means the
--     date keeps its day-of-week schedule type.
--   * atypical — the agency-declared atypical-day flag (v0: declared only).
--   * meaningful CHECK — a row that neither reassigns nor flags declares
--     nothing and is unrepresentable.
--   * reason — required, non-blank: every calendar declaration must be
--     explainable to a transit operations manager.

CREATE TABLE app.service_day_overrides (
    service_date       DATE PRIMARY KEY,
    assigned_day_type  TEXT
        CONSTRAINT service_day_overrides_day_type_vocabulary
        CHECK (assigned_day_type IN ('weekday', 'saturday', 'sunday')),
    atypical           BOOLEAN NOT NULL DEFAULT false,
    reason             TEXT NOT NULL
        CONSTRAINT service_day_overrides_reason_not_blank
        CHECK (length(btrim(reason)) > 0),
    updated_by         TEXT NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT service_day_overrides_meaningful
        CHECK (assigned_day_type IS NOT NULL OR atypical)
);

COMMENT ON TABLE app.service_day_overrides IS
    'Agency-declared service-day overrides (handoff 0020): holiday day-type '
    'reassignments (2026 NTD Policy Manual p. 156) and atypical-day flags. '
    'Audited writes via the settings API; consumed by calc daytype_v0, which '
    'snapshots each governing row into the figure''s detail JSONB.';
