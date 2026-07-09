-- 0001: extensions and schemas for canonical schema contract v0
-- (docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md)
-- PostgreSQL 16 ships gen_random_uuid() in core, so pgcrypto is NOT required.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- One database per agency; no per-tenant discriminator column anywhere (ADR-0004).
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS canonical;
CREATE SCHEMA IF NOT EXISTS computed;
CREATE SCHEMA IF NOT EXISTS lineage;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS cert;
