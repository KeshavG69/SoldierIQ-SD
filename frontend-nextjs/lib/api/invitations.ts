import apiClient from './client';

export interface OrgInvitation {
  id: string;
  email: string;
  role: string;
  createdAt?: string;
}

export interface ValidateInvitationResponse {
  email: string;
  organization_name?: string;
  role: string;
  user_exists: boolean;
}

export interface AcceptInvitationPayload {
  invitation_id: string;
  organization_id: string;
  firstName?: string;
  lastName?: string;
  password?: string;
}

export const invitationsApi = {
  // --- admin ---
  send: async (email: string, role: 'admin' | 'user') => {
    const res = await apiClient.post('/invitations', { email, role });
    return res.data as { invitation_id: string; accept_url: string; email: string; role: string; emailed: boolean };
  },
  list: async (): Promise<OrgInvitation[]> => {
    const res = await apiClient.get<OrgInvitation[]>('/invitations');
    return res.data;
  },
  revoke: async (id: string): Promise<void> => {
    await apiClient.delete(`/invitations/${id}`);
  },

  // --- public (accept page) ---
  validate: async (inv: string, org: string): Promise<ValidateInvitationResponse> => {
    const res = await apiClient.get<ValidateInvitationResponse>('/invitations/validate', {
      params: { inv, org },
    });
    return res.data;
  },
  accept: async (payload: AcceptInvitationPayload) => {
    const res = await apiClient.post('/invitations/accept', payload);
    return res.data as {
      organization_id: string;
      access_token?: string;
      refresh_token?: string;
    };
  },
};
