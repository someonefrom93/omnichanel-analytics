-- Migration: 001_create_pipeline_execution_logs
-- Target: PostgreSQL 14+
-- Schema source: locked in PR1 design.md
--   (openspec/changes/real-adapters-pr1/design.md §Locked decisions)
-- Idempotent: uses IF NOT EXISTS so re-running is safe

CREATE TABLE IF NOT EXISTS pipeline_execution_logs (
    id            UUID         PRIMARY KEY,
    merchant_id   TEXT         NOT NULL,
    run_id        UUID         NOT NULL,
    pipeline_name TEXT         NOT NULL,
    status        TEXT         NOT NULL CHECK (status IN ('STARTED', 'SUCCESS', 'FAILED')),
    started_at    TIMESTAMPTZ  NOT NULL,
    finished_at   TIMESTAMPTZ,
    error_class   TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_execution_logs_merchant_started
    ON pipeline_execution_logs (merchant_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_execution_logs_run_id
    ON pipeline_execution_logs (run_id);