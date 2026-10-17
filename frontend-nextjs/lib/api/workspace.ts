import apiClient from './client';

export interface WorkspaceOrganization {
  id: string;
  name: string;
  role: string;
  status: string;
  is_current: boolean;
}

export interface SavedSelection {
  saved: boolean; // false = the user never saved one (keep the local selection)
  document_ids: string[];
}

export const workspaceApi = {
  // Document selection saved server-side (Postgres) for the active org.
  getSelection: async (): Promise<SavedSelection> => {
    const res = await apiClient.get<SavedSelection>('/workspace/selection');
    return res.data;
  },

  saveSelection: async (documentIds: string[]): Promise<void> => {
    await apiClient.put('/workspace/selection', { document_ids: documentIds });
  },

  // Organizations the current user belongs to.
  getUserOrganizations: async (): Promise<WorkspaceOrganization[]> => {
    const res = await apiClient.get<WorkspaceOrganization[]>('/workspace/organizations');
    return res.data;
  },

  // Switch active org. The backend returns a fresh token set (no re-login);
  // store it so subsequent requests are scoped to the new org.
  switchOrganization: async (organizationId: string): Promise<void> => {
    const res = await apiClient.post('/workspace/switch', { organization_id: organizationId });
    if (res.data?.access_token) {
      localStorage.setItem('access_token', res.data.access_token);
      if (res.data.refresh_token) localStorage.setItem('refresh_token', res.data.refresh_token);
    }
  },
};
