import apiClient, { fetchWithRefresh } from './client';

export interface FormatSuggestion {
  name: string;
  description: string;
  prompt: string;
}

export interface SuggestionsResponse {
  status: 'not_found' | 'processing' | 'completed' | 'failed';
  suggestions: FormatSuggestion[] | null;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export const reportsApi = {
  // Trigger format suggestions generation
  triggerFormatSuggestions: async (documentIds: string[]): Promise<{ workflow_id: string; status: string; message: string }> => {
    const response = await apiClient.post('/report-suggestions/suggest-formats', {
      document_ids: documentIds,
      // user_id and organization_id are extracted from JWT token by backend
    });

    return response.data;
  },

  // Get format suggestions (for polling)
  getSuggestions: async (documentIds: string[]): Promise<SuggestionsResponse> => {
    const response = await apiClient.post<SuggestionsResponse>('/report-suggestions/get-suggestions', {
      document_ids: documentIds,
    });

    return response.data;
  },

  // Generate report with streaming
  generateReport: async (
    documentIds: string[],
    prompt: string
  ): Promise<ReadableStream> => {
    // Use fetchWithRefresh for automatic token refresh on 401
    const response = await fetchWithRefresh(`${process.env.NEXT_PUBLIC_API_URL}/api/reports/generate`, {
      method: 'POST',
      body: JSON.stringify({
        document_ids: documentIds,
        prompt,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Report generation failed');
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    return response.body;
  },
};
