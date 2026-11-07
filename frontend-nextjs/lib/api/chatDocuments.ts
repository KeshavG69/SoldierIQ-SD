import apiClient from './client';

// Documents the chat agent builds (build_document) live in iDrive E2 under
// chat-documents/<org>/…; the backend signs a fresh download link on request.
export const chatDocumentsApi = {
  downloadUrl: async (objectKey: string): Promise<string> =>
    (
      await apiClient.get<{ url: string; filename: string }>('/chat/documents/download-url', {
        params: { key: objectKey },
      })
    ).data.url,
};
