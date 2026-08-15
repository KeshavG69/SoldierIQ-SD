-- ============================================================================
-- VECTOR DATABASE SCHEMA
-- SoldierIQ Knowledge Management System
-- Generated: 2026-03-09 04:13:38
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================================
-- TABLE: langchain_pg_collection
-- Current rows: 1
-- ============================================================================

-- Indexes for langchain_pg_collection
CREATE UNIQUE INDEX langchain_pg_collection_name_key ON public.langchain_pg_collection USING btree (name);

-- ============================================================================
-- TABLE: langchain_pg_embedding
-- Current rows: 5
-- ============================================================================

-- Indexes for langchain_pg_embedding
CREATE INDEX IF NOT EXISTS idx_langchain_document_id ON public.langchain_pg_embedding USING btree (((cmetadata ->> 'document_id'::text)));
CREATE INDEX IF NOT EXISTS idx_langchain_org_user ON public.langchain_pg_embedding USING btree (((cmetadata ->> 'organization_id'::text)), ((cmetadata ->> 'user_id'::text)));
CREATE INDEX IF NOT EXISTS ix_cmetadata_gin ON public.langchain_pg_embedding USING gin (cmetadata jsonb_path_ops);

-- ============================================================================
-- TABLE: vector_embeddings
-- Current rows: 0
-- ============================================================================

-- Indexes for vector_embeddings
CREATE INDEX IF NOT EXISTS idx_vectors_document_id ON public.vector_embeddings USING btree (document_id);
CREATE INDEX IF NOT EXISTS idx_vectors_embedding_hnsw ON public.vector_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_vectors_kb_name ON public.vector_embeddings USING btree (kb_name);
CREATE INDEX IF NOT EXISTS idx_vectors_metadata ON public.vector_embeddings USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_vectors_org_user ON public.vector_embeddings USING btree (organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_vectors_org_user_doc ON public.vector_embeddings USING btree (organization_id, user_id, document_id);

