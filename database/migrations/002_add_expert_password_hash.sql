-- Migration: 002_add_expert_password_hash
-- Description: Add password_hash column to experts table for JWT authentication

BEGIN;

ALTER TABLE experts
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

COMMIT;
