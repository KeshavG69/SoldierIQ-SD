import apiClient from './client';

export type SlideDeckFormat = 'detailed' | 'presenter';
export type SlideDeckLength = 'short' | 'default' | 'long';
export type SlideDeckStyle = 'auto' | 'professional' | 'tactical' | 'editorial' | 'instructional' | 'sketch';
export type SlideDeckStatus = 'processing' | 'completed' | 'failed';
export type SlideDeckStage = 'queued' | 'reading' | 'designing' | 'rendering' | 'completed' | 'failed';

export interface SlideDeckOptions {
  format: SlideDeckFormat;
  length: SlideDeckLength;
  style: SlideDeckStyle;
  focus?: string;
}

export interface SlideDeckSettings {
  format?: SlideDeckFormat;
  length?: SlideDeckLength;
  style?: SlideDeckStyle;
  focus?: string | null;
}

export interface SlideDeckSummary {
  workflow_id: string;
  status: SlideDeckStatus;
  stage: SlideDeckStage | null;
  title: string | null;
  settings: SlideDeckSettings;
  slide_count: number;
  document_count: number;
  thumbnail_url: string | null;
  created_at: string | null;
}

export interface SlideDeckData {
  workflow_id: string;
  status: SlideDeckStatus;
  stage: SlideDeckStage | null;
  title: string | null;
  settings: SlideDeckSettings;
  slide_count: number;
  slide_urls: string[];
  notes: string[];
  sources: string[];
  document_ids: string[];
  document_count: number;
  error: string | null;
  pptx_url: string | null;
  pdf_url: string | null;
  created_at: string | null;
}

interface ApiResponse<T> {
  status: string;
  data: T;
}

interface StartResponse {
  workflow_id: string;
  status: SlideDeckStatus;
}

export const slideDeckApi = {
  /**
   * Start generating a slide deck (runs in the background; poll getById)
   */
  generate: async (documentIds: string[], options: SlideDeckOptions): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>('/slide-deck/generate', {
      document_ids: documentIds,
      ...options,
      // user_id and organization_id are extracted from JWT token by backend
    });
    return response.data.data;
  },

  /**
   * Generate a new deck with the same documents and settings as an existing one
   */
  regenerate: async (workflowId: string): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>(`/slide-deck/${workflowId}/regenerate`);
    return response.data.data;
  },

  /**
   * List the current user's slide decks (newest first), including in-progress ones
   */
  list: async (): Promise<SlideDeckSummary[]> => {
    const response = await apiClient.get<ApiResponse<SlideDeckSummary[]>>('/slide-deck/list');
    return response.data.data;
  },

  /**
   * Get a deck's status and, once completed, its slide images and download links
   */
  getById: async (workflowId: string): Promise<SlideDeckData> => {
    const response = await apiClient.get<ApiResponse<SlideDeckData>>(`/slide-deck/${workflowId}`);
    return response.data.data;
  },
};
