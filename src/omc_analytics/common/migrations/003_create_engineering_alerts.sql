-- Migration: 003_create_engineering_alerts
-- Target: PostgreSQL 14+
-- Schema: id, source, severity, error_class, error_message, stack_trace, created_at
-- Idempotent: uses IF NOT EXISTS so re-running is safe

CREATE TABLE IF NOT EXISTS engineering_alerts (
    id            UUID         PRIMARY KEY,
    source        TEXT         NOT NULL,
    severity      TEXT         NOT NULL,
    error_class   TEXT         NOT NULL,
    error_message TEXT         NOT NULL,
    stack_trace   TEXT,
    created_at    TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_engineering_alerts_created_at
    ON engineering_alerts (created_at DESC);
