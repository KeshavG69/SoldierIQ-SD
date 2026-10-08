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

/**
 * Read a report SSE stream to completion and return the report markdown.
 * Throws with the backend's message on an `error` event or an empty report.
 */
export async function readReportStream(stream: ReadableStream): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();

  let fullReportContent = '';
  let streamError = '';
  let buffer = '';

  // One SSE frame: "event: <name>\ndata: <json>". Frames are split on the
  // blank line that terminates them (never on '\n' alone) — the report is
  // tens of KB, so its event and data lines routinely land in different
  // network chunks, and a line-at-a-time reader drops the pair.
  const handleFrame = (frame: string) => {
    let event = 'message';
    const dataLines: string[] = [];

    for (const rawLine of frame.split('\n')) {
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
      if (!line || line.startsWith(':')) continue; // blank or comment/keepalive
      if (line.startsWith('event:')) {
        event = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        // A leading space after "data:" is part of the SSE framing, not the payload.
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
    }

    if (dataLines.length === 0) return;

    let data: any;
    try {
      data = JSON.parse(dataLines.join('\n'));
    } catch {
      return; // Not JSON (e.g. "[DONE]") — nothing to take from it.
    }

    if (event === 'report') {
      fullReportContent = data.content || '';
    } else if (event === 'error') {
      // Recorded, not thrown: throwing from here would only unwind the
      // reader loop mid-stream.
      streamError = data.error || 'Unknown error occurred';
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let sep = buffer.indexOf('\n\n');
    while (sep !== -1) {
      handleFrame(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
      sep = buffer.indexOf('\n\n');
    }
  }

  // A final frame that arrived without its terminating blank line.
  if (buffer.trim()) handleFrame(buffer);

  if (streamError) throw new Error(streamError);
  if (!fullReportContent.trim()) throw new Error('Report generation finished without returning any content');
  return fullReportContent;
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
