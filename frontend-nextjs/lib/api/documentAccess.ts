import apiClient from './client';

export interface DocumentAccess {
  document_id: string;
  emails: string[];
}

/**
 * Per-document RBAC (admin only).
 *
 * The backend gates every one of these on org-admin. Admins implicitly see
 * every document; these endpoints control which *members* may see and query a
 * specific file. Access is keyed by email (graph HAS_ACCESS edges).
 */
export const documentAccessApi = {
  // Emails that have been granted access to this document.
  getAccess: async (documentId: string): Promise<DocumentAccess> => {
    const res = await apiClient.get<DocumentAccess>(
      `/documents/${encodeURIComponent(documentId)}/access`
    );
    return res.data;
  },

  // Grant a member (by email) access to this document.
  grant: async (documentId: string, email: string): Promise<void> => {
    await apiClient.post(`/documents/${encodeURIComponent(documentId)}/access`, { email });
  },

  // Revoke a member's access. `email` goes as a query param (matches backend).
  revoke: async (documentId: string, email: string): Promise<void> => {
    await apiClient.delete(`/documents/${encodeURIComponent(documentId)}/access`, {
      params: { email },
    });
  },
};
