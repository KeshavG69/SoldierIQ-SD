-- ============================================================================
-- GRAPH DATABASE SCHEMA
-- SoldierIQ Knowledge Management System
-- Apache AGE (PostgreSQL extension for graph databases)
-- Generated: 2026-03-09 04:14:35
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "age";

-- Load AGE extension
LOAD 'age';
SET search_path = ag_catalog, '$user', public;

-- Create graph (if not exists)
SELECT create_graph('knowledge_graph');

