import apiClient from './client';

export interface WorkspaceOrganization {
  id: string;
  name: string;
  role: string;
  status: string;
  is_current: boolean;
}

export const workspaceApi = {
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
