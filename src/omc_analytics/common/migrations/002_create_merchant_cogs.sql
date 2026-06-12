-- Migration: 002_create_merchant_cogs
-- Target: PostgreSQL 14+
-- Schema: merchant-specific COGS (Cost of Goods Sold) editor table
-- Idempotent: uses IF NOT EXISTS so re-running is safe

CREATE TABLE IF NOT EXISTS merchant_cogs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     TEXT NOT NULL,
    line_item_sku   TEXT NOT NULL,
    recipe_cost     DECIMAL(10,4) NOT NULL DEFAULT 0,
    packaging_cost  DECIMAL(10,4) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, line_item_sku)
);

CREATE INDEX IF NOT EXISTS idx_merchant_cogs_merchant
    ON merchant_cogs (merchant_id);
