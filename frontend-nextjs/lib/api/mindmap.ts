import apiClient from './client';

// Mind Map Types
export interface MindMapNode {
  id: string;
  content: string;
}

export interface MindMapEdge {
  from_id: string;
  to_id: string;
}

export interface MindMapData {
  nodes: MindMapNode[];
  edges: MindMapEdge[];
}

export interface MindMapResponse {
  success: boolean;
  mind_map_id: string;
  document_ids: string[];
  document_count: number;
  summary: string;
  key_points: string[];
  mind_map: MindMapData;
  node_count: number;
  edge_count: number;
}

export interface MindMapListResponse {
  success: boolean;
  data: MindMapResponse[];
  count: number;
}

export const mindmapApi = {
  // Generate mind map from selected documents
  generate: async (documentIds: string[]): Promise<MindMapResponse> => {
    const response = await apiClient.post<MindMapResponse>('/mindmap/generate', {
      document_ids: documentIds
    });
    return response.data;
  },

  // Get mind map by ID
  getById: async (mindMapId: string): Promise<MindMapResponse> => {
    const response = await apiClient.get<{ success: boolean; data: MindMapResponse }>(`/mindmap/${mindMapId}`);
    return response.data.data;
  },

  // List all mind maps for current user and organization
  list: async (): Promise<MindMapResponse[]> => {
    // user_id and organization_id are extracted from JWT token by backend
    const response = await apiClient.get<MindMapListResponse>(`/mindmap/list`);
    return response.data.data;
  },
};
