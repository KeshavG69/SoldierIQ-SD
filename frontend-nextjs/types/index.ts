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
  documents?: GeneratedDocument[]; // build_document results → download cards
  toolCalls?: ToolCallStep[]; // live timeline of the agent's tool calls
  briefing?: { suggestions: string[] }; // login briefing → clickable follow-ups
  maps?: MapCardInfo[]; // show_map results → interactive intelligence map cards
  charts?: ChartSpec[]; // create_chart results → chart / timeline cards
}

// ── Visual answers (backend/utils/visual_tools.py) ──────────────────────────

export type IntelSeverity = 'critical' | 'high' | 'elevated' | 'moderate' | 'low' | 'info';

export interface MapLayerInfo {
  id: string; // strikes | aircraft | conflict | chokepoints | hotspots | quakes | disasters | outages | fires | ships
  label: string;
  icon: string;
  count: number;
}

// What the chat message keeps (small); the full payload is fetched by map_id.
export interface MapCardInfo {
  map_id: string;
  title: string;
  region: string;
  bbox: [number, number, number, number] | null; // west, south, east, north
  hours: number;
  icon_count: number;
  layers: MapLayerInfo[];
  notes?: string[];
}

export interface MapFeature {
  id: string;
  layer: string;
  lat: number;
  lon: number;
  title: string;
  time: string | null;
  severity: IntelSeverity;
  verdict?: string | null;
  heading?: number | null;
  source: string;
  url?: string | null;
  text?: string | null;
  radius_km?: number;
  details: Record<string, string | number | boolean | null>;
}

export interface MapPayload {
  type: 'map';
  title: string;
  region: string;
  bbox: [number, number, number, number] | null;
  hours: number;
  layers: MapLayerInfo[];
  features: MapFeature[];
  sources: { name: string; ok: boolean; fetched_at?: string | null }[];
  notes: string[];
}

export interface ChartSpec {
  type: 'chart';
  kind: 'bar' | 'column' | 'line' | 'area' | 'donut' | 'timeline';
  title: string;
  subtitle?: string | null;
  source?: string | null;
  categories?: string[];
  series?: { name: string; data: (number | null)[] }[];
  x_title?: string | null;
  y_title?: string | null;
  value_format?: 'number' | 'percent' | 'currency';
  events?: { time: string; label: string; detail?: string | null; severity?: IntelSeverity | null }[];
}

// A file the agent built with build_document (stored in iDrive E2)
export interface GeneratedDocument {
  slug: string;
  filename: string;
  format?: string; // pdf | docx | pptx | xlsx
  url: string; // presigned link from the tool (expires)
  object_key?: string; // used to sign a fresh link on download
  preview_key?: string | null; // PDF rendering for the preview pane
  size_bytes?: number;
  version?: number;
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
  reconnect?: boolean; // connected with limited permissions → offer to reconnect
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
