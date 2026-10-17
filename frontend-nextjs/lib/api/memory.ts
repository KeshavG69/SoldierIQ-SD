import apiClient from './client';

export interface Memory {
  id: string;
  memory: string;
  topics: string[];
  created_at: number | null; // epoch seconds
  updated_at: number | null;
}

export interface MemoryList {
  memories: Memory[];
  limit: number; // max memories kept per user (oldest are dropped)
}

// What the chat agent remembers about the current user (active org).
export const memoryApi = {
  list: async (): Promise<MemoryList> => (await apiClient.get<MemoryList>('/memory')).data,

  add: async (memory: string, topics?: string[]): Promise<Memory> =>
    (await apiClient.post<Memory>('/memory', { memory, topics })).data,

  update: async (id: string, memory: string, topics?: string[]): Promise<Memory> =>
    (await apiClient.put<Memory>(`/memory/${encodeURIComponent(id)}`, { memory, topics })).data,

  remove: async (id: string): Promise<void> => {
    await apiClient.delete(`/memory/${encodeURIComponent(id)}`);
  },

  clear: async (): Promise<number> => (await apiClient.delete<{ deleted: number }>('/memory')).data.deleted,
};
