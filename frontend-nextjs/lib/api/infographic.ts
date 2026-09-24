import apiClient from './client';

export type InfographicOrientation = 'portrait' | 'landscape' | 'square';
export type InfographicDetailLevel = 'concise' | 'standard' | 'detailed';
export type InfographicStyle = 'auto' | 'professional' | 'tactical' | 'editorial' | 'instructional' | 'sketch';
export type InfographicStatus = 'processing' | 'completed' | 'failed';

export interface InfographicOptions {
  orientation: InfographicOrientation;
  detail_level: InfographicDetailLevel;
  style: InfographicStyle;
  focus?: string;
}

export interface InfographicSettings {
  orientation?: InfographicOrientation;
  detail_level?: InfographicDetailLevel;
  style?: InfographicStyle;
  focus?: string | null;
}

export interface InfographicSummary {
  workflow_id: string;
  status: InfographicStatus;
  title: string | null;
  settings: InfographicSettings;
  document_count: number;
  image_url: string | null;
  created_at: string | null;
}

export interface InfographicData extends InfographicSummary {
  sources: string[];
  document_ids: string[];
  error: string | null;
  download_url: string | null;
}

interface ApiResponse<T> {
  status: string;
  data: T;
}

interface StartResponse {
  workflow_id: string;
  status: InfographicStatus;
}

export const infographicApi = {
  /**
   * Start generating an infographic (runs in the background; poll getById)
   */
  generate: async (documentIds: string[], options: InfographicOptions): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>('/infographic/generate', {
      document_ids: documentIds,
      ...options,
      // user_id and organization_id are extracted from JWT token by backend
    });
    return response.data.data;
  },

  /**
   * Generate a new infographic with the same documents and settings as an existing one
   */
  regenerate: async (workflowId: string): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>(`/infographic/${workflowId}/regenerate`);
    return response.data.data;
  },

  /**
   * List the current user's infographics (newest first), including in-progress ones
   */
  list: async (): Promise<InfographicSummary[]> => {
    const response = await apiClient.get<ApiResponse<InfographicSummary[]>>('/infographic/list');
    return response.data.data;
  },

  /**
   * Get an infographic's status and image URLs
   */
  getById: async (workflowId: string): Promise<InfographicData> => {
    const response = await apiClient.get<ApiResponse<InfographicData>>(`/infographic/${workflowId}`);
    return response.data.data;
  },
};
