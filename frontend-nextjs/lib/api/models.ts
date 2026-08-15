import apiClient from './client';

export interface Model {
  id: string;
  name: string;
}

export interface ModelsResponse {
  success: boolean;
  models: Model[];
  count: number;
}

export const modelsApi = {
  // Get list of available models
  list: async (): Promise<Model[]> => {
    const response = await apiClient.get<ModelsResponse>('/models');
    return response.data.models;
  },
};
