-- Minimal initialization - Alembic handles all schema
-- This just ensures pgvector extension is available

CREATE EXTENSION IF NOT EXISTS vector;
