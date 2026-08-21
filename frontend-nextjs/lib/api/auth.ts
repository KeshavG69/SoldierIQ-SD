import apiClient from './client';

// Types
export interface User {
  id: string;
  username: string;
  email: string;
  firstName?: string;
  lastName?: string;
  email_verified: boolean;
  roles: string[];
  organization_id?: string;
  organization_name?: string;
  role?: 'admin' | 'system_owner' | 'user' | string;  // role in the active organization
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface SignupData {
  username: string;
  email: string;
  password: string;
  firstName: string;
  lastName: string;
}

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

interface SignupResponse {
  id: string;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  organization_id: string;
  organization_name: string;
  message: string;
}

export const authApi = {
  // Sign up new user
  signup: async (data: SignupData): Promise<SignupResponse> => {
    const response = await apiClient.post<SignupResponse>('/auth/signup', data);
    return response.data;
  },

  // Login user
  login: async (credentials: LoginCredentials): Promise<LoginResponse> => {
    const response = await apiClient.post<LoginResponse>('/auth/login', credentials);
    return response.data;
  },

  // Get current user
  getCurrentUser: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me');
    return response.data;
  },

  // Logout
  logout: async (): Promise<void> => {
    const refreshToken = localStorage.getItem('refresh_token');
    await apiClient.post('/auth/logout', {
      refresh_token: refreshToken
    });
  },
};
