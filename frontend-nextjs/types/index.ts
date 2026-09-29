// Auth Types
export interface User {
  id: string;
  email: string;
  firstName?: string;
  lastName?: string;
  organization_id: string;
}

// Document Types
export interface Document {
  id: string;  // Changed from _id (MongoDB) to id (PostgreSQL)
  file_name: string;
  folder_name?: string;
  user_id: string;
  organization_id: string;
  created_at: string;
  updated_at: string;
  // Present in the list response to signal "a downloadable file exists". The
  // actual presigned download URL is fetched on demand (GET /documents/{id})
  // when the user clicks the filename — not pre-generated for every doc.
  file_key?: string;
  file_url?: string;
  // Processing status fields
  status?: 'processing' | 'completed' | 'failed';
  processing_stage?: string;
  processing_stage_description?: string;
  processing_progress?: {
    current: number;
    total: number;
    percentage: number;
  };
  error?: string;
  completed_at?: string;
  failed_at?: string;
  // Arbitrary metadata stamped at ingest time (e.g. { source: 'google_drive',
  // drive_file_id, drive_file_name }).
  metadata?: Record<string, any>;
}

// Knowledge Base Types
export interface KnowledgeBase {
  name: string;
  folder_name: string;
  document_count: number;
  display_name: string;
}

// Chat Types
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  sources?: any[]; // Sources specific to this message
  graph?: KnowledgeGraph; // GraphRAG retrieval graph (entities + triples + chunks)
  composioAuth?: ComposioAuthInfo; // setup_composio_service result → "Connect <app>" card
  toolCalls?: ToolCallStep[]; // live timeline of the agent's tool calls
}

// One tool call in an assistant message's step timeline
export interface ToolCallStep {
  id: string;
  name: string;
  status: 'running' | 'done' | 'error';
  label: string; // shown while running, e.g. "Searching your documents"
  doneLabel: string; // shown when finished, e.g. "Searched your documents"
  detail?: string | null; // short argument summary, e.g. the search query
  app?: string | null; // app title for Composio tools, e.g. "Gmail"
  logo?: string | null;
  icon?: string | null; // built-in icon key: search | map | message | route | plug | app | tool
  args?: Record<string, unknown>;
  resultPreview?: string; // truncated result, kept small for localStorage
  startedAt: number;
  duration?: number; // seconds
}

// Result of the agent's setup_composio_service tool, rendered as a connect card
export interface ComposioAuthInfo {
  service: string;
  service_title: string;
  logo?: string | null;
  already_connected: boolean;
  actions_added: string[];
}

// Knowledge-graph payload returned by the GraphRAG search tool
export interface KnowledgeGraphAnchor {
  name: string;
  type?: string | null;
  chunk_count: number;
}

export interface KnowledgeGraphTriple {
  subject: string;
  subject_type?: string | null;
  predicate: string;
  object: string;
  object_type?: string | null;
  confidence?: number | null;
  source_chunk?: string | null;
}

export interface KnowledgeGraphChunk {
  chunk_id: string;
  document_id: string;
  text: string;
  score: number | null;
  shared_entities: number | null;
  via: 'vector' | 'graph';
}

export interface KnowledgeGraph {
  anchors: KnowledgeGraphAnchor[];
  triples: KnowledgeGraphTriple[];
  chunks: KnowledgeGraphChunk[];
  query?: string;
}

export interface SourceReference {
  document_id: string;
  filename: string;
  text?: string;
  file_key?: string;
  page_number?: number;
  snippet?: string;
  folder_name?: string;
}
