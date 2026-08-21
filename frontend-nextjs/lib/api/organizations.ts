import apiClient from './client';

export interface OrgMember {
  user_id: string;
  username?: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  role: string;
  is_self: boolean;
}

export const organizationsApi = {
  listMembers: async (): Promise<OrgMember[]> => {
    const res = await apiClient.get<OrgMember[]>('/organizations/me/members');
    return res.data;
  },
  removeMember: async (userId: string): Promise<void> => {
    await apiClient.delete(`/organizations/members/${userId}`);
  },
  changeMemberRole: async (userId: string, role: 'admin' | 'system_owner' | 'user'): Promise<void> => {
    await apiClient.post(`/organizations/members/${userId}/role`, { role });
  },
};
