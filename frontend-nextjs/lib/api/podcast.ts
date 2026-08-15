import apiClient from './client';

export interface PodcastEpisode {
  id: string;  // Changed from _id (MongoDB) to id (PostgreSQL)
  organization_id: string;
  document_ids: string[];
  title?: string;
  summary?: string;
  audio_file_key?: string;
  status: 'processing' | 'script_generated' | 'completed' | 'failed';
  error_message?: string;
  created_at: string;
  script?: any;
}

export interface PodcastGenerationResponse {
  episode_id: string;
  status: string;
  message: string;
}

export const podcastApi = {
  // Start podcast generation
  generatePodcast: async (documentIds: string[]): Promise<PodcastGenerationResponse> => {
    const response = await apiClient.post<PodcastGenerationResponse>('/podcasts/generate', {
      document_ids: documentIds
      // organization_id extracted from JWT token by backend
    });

    return response.data;
  },

  // Get podcast status/result by episode ID
  getPodcastStatus: async (episodeId: string): Promise<PodcastEpisode> => {
    const response = await apiClient.get<PodcastEpisode>(`/podcasts/${episodeId}`);
    return response.data;
  },
  
  // Get Presigned URL for Audio
  // Assuming there is a generic file access endpoint or we use the file_key directly with a signer
  // For now, let's assume the backend might provide a signed URL or we use the existing s3-signer if available.
  // But based on the backend implementation, the client receives a file_key. 
  // We might need a way to fetch the actual URL.
  // Checking backend routers/files.py or similar would be good, but for now we will stick to the core podcast endpoints.
};
