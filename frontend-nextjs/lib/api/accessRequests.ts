import apiClient from './client';

export interface AccessRequest {
  id: string;
  requester_email: string;
  requester_name?: string | null;
  message?: string | null;
  created_at?: string | null;
}

export const accessRequestsApi = {
  // Public: submit a request for System Owner access, addressed to an admin.
  submit: async (payload: {
    requester_email: string;
    admin_email: string;
    requester_name?: string;
    message?: string;
  }): Promise<{ message: string }> => {
    const res = await apiClient.post('/access-requests', payload);
    return res.data;
  },

  // Admin: pending requests addressed to me, for the active org.
  list: async (): Promise<AccessRequest[]> => {
    const res = await apiClient.get<AccessRequest[]>('/access-requests');
    return res.data;
  },

  // Admin: approve for the active org (sends the requester a System Owner invite).
  approve: async (id: string) => {
    const res = await apiClient.post(`/access-requests/${id}/approve`);
    return res.data as { message: string; requester_email: string; accept_url: string | null; emailed: boolean };
  },

  // Admin: deny the request entirely.
  deny: async (id: string): Promise<void> => {
    await apiClient.post(`/access-requests/${id}/deny`);
  },
};
