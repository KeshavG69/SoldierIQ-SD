-- ============================================================================
-- MAIN DATABASE SCHEMA
-- SoldierIQ Knowledge Management System
-- Generated: 2026-03-09 04:13:24
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- TABLE: documents
-- Current rows: 5
-- ============================================================================

-- Indexes for documents
CREATE INDEX IF NOT EXISTS idx_documents_created ON public.documents USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_folder ON public.documents USING btree (folder_name);
CREATE INDEX IF NOT EXISTS idx_documents_metadata ON public.documents USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_documents_org_user ON public.documents USING btree (organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON public.documents USING btree (status);

-- ============================================================================
-- TABLE: podcasts
-- Current rows: 0
-- ============================================================================

-- Indexes for podcasts
CREATE INDEX IF NOT EXISTS idx_podcasts_created ON public.podcasts USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_podcasts_org_user ON public.podcasts USING btree (organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_podcasts_status ON public.podcasts USING btree (status);

-- ============================================================================
-- TABLE: tak_configuration
-- Current rows: 0
-- ============================================================================

-- Indexes for tak_configuration
CREATE INDEX IF NOT EXISTS idx_tak_config_enabled ON public.tak_configuration USING btree (tak_enabled);
CREATE INDEX IF NOT EXISTS idx_tak_config_org ON public.tak_configuration USING btree (organization_id);
CREATE UNIQUE INDEX tak_configuration_organization_id_key ON public.tak_configuration USING btree (organization_id);

-- ============================================================================
-- TABLE: workflows
-- Current rows: 0
-- ============================================================================

-- Indexes for workflows
CREATE INDEX IF NOT EXISTS idx_workflows_created ON public.workflows USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflows_document_ids ON public.workflows USING gin (document_ids);
CREATE INDEX IF NOT EXISTS idx_workflows_org_user ON public.workflows USING btree (organization_id, user_id);
CREATE INDEX IF NOT EXISTS idx_workflows_type ON public.workflows USING btree (type);
CREATE INDEX IF NOT EXISTS idx_workflows_user ON public.workflows USING btree (user_id);


-- ============================================================================
-- TABLE: google_drive_connections
-- One row per (organization_id, user_id) pair. Stores OAuth tokens for the
-- user's connected Google Drive. Refresh tokens never expire (until revoked);
-- access tokens get refreshed lazily by GoogleDriveClient when expired.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.google_drive_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL,
    user_id UUID NOT NULL,
    email TEXT,
    display_name TEXT,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    access_token_expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_gdrive_org_user
    ON public.google_drive_connections USING btree (organization_id, user_id);

-- Flag set when a token refresh fails with invalid_grant (user revoked the
-- app, or the refresh token expired). The UI shows a "reconnect" banner.
ALTER TABLE public.google_drive_connections
    ADD COLUMN IF NOT EXISTS needs_reconnect BOOLEAN NOT NULL DEFAULT FALSE;


-- ============================================================================
-- TABLE: composio_connections
-- One row per (organization_id, user_id, service): a third-party app the user
-- connected through Composio for the chat agent (Gmail, Slack, Jira, …).
-- Composio holds the OAuth tokens; we only keep its connected_account_id.
-- status: INITIATED/INITIALIZING while OAuth is in progress, ACTIVE once done.
-- The app catalog + allowed actions live in config/composio_connectors.json.
-- Also created on backend startup by clients/composio_connectors.py.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.composio_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    service TEXT NOT NULL,
    toolkit TEXT NOT NULL,
    connected_account_id TEXT,
    status TEXT NOT NULL DEFAULT 'INITIATED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id, service)
);

CREATE INDEX IF NOT EXISTS idx_composio_conn_account
    ON public.composio_connections USING btree (connected_account_id);


-- ============================================================================
-- Connector catalog + per-user action toggles (mirrors enterprise's Mongo
-- Tool / ToolAction / ChatTool / ChatAction collections).
--   connector_tools          one row per app (Gmail, Slack, …)
--   connector_tool_actions   one row per Composio action of an app
--   user_connector_tools     a user's on/off switch for an app
--   user_connector_actions   a user's on/off switch for one action
-- The catalog is seeded/upserted from config/composio_connectors.json on
-- backend startup; toggles default to off (no row = disabled). The chat agent
-- only gets actions that are enabled, on an enabled app, that is connected.
-- Also created on startup by clients/composio_connectors.py.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.connector_tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,              -- service key, e.g. 'gmail'
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    logo TEXT,
    toolkit TEXT NOT NULL,                  -- Composio toolkit slug
    auth_config_id TEXT,                    -- optional pinned Composio auth config
    status TEXT NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE | INACTIVE
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.connector_tool_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id UUID NOT NULL REFERENCES public.connector_tools(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE,              -- Composio action slug, e.g. GMAIL_SEND_EMAIL
    title TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL DEFAULT 'read',      -- read | write
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_connector_actions_tool ON public.connector_tool_actions (tool_id);

CREATE TABLE IF NOT EXISTS public.user_connector_tools (
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    tool_id UUID NOT NULL REFERENCES public.connector_tools(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id, tool_id)
);

CREATE TABLE IF NOT EXISTS public.user_connector_actions (
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    action_id UUID NOT NULL REFERENCES public.connector_tool_actions(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id, action_id)
);
-- Enabled-action lookups (limit count, agent tools, Connectors screen).
CREATE INDEX IF NOT EXISTS idx_user_connector_actions_enabled
    ON public.user_connector_actions (organization_id, user_id) WHERE enabled;
