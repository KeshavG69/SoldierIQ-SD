import apiClient from './client';

export type VideoFormat = 'explainer' | 'brief';
export type VideoStyle = 'classic' | 'whiteboard' | 'watercolor' | 'papercraft' | 'retro_print' | 'tactical';
export type VideoVoice = 'sarah' | 'brian' | 'george';
export type VideoStatus = 'processing' | 'completed' | 'failed';
export type VideoStage =
  | 'queued'
  | 'reading'
  | 'scripting'
  | 'illustrating'
  | 'narrating'
  | 'composing'
  | 'completed'
  | 'failed';

export interface VideoOptions {
  format: VideoFormat;
  style: VideoStyle;
  voice: VideoVoice;
  focus?: string;
}

export interface VideoSettings {
  format?: VideoFormat;
  style?: VideoStyle;
  voice?: VideoVoice;
  focus?: string | null;
}

export interface VideoChapter {
  title: string;
  start: number;
  thumb_url: string | null;
}

export interface VideoSummary {
  workflow_id: string;
  status: VideoStatus;
  stage: VideoStage | null;
  title: string | null;
  settings: VideoSettings;
  duration_s: number | null;
  document_count: number;
  poster_url: string | null;
  created_at: string | null;
}

export interface VideoData {
  workflow_id: string;
  status: VideoStatus;
  stage: VideoStage | null;
  title: string | null;
  settings: VideoSettings;
  duration_s: number | null;
  chapters: VideoChapter[];
  captions_vtt: string | null;
  transcript: string[];
  sources: string[];
  tts_engines: string[];
  document_ids: string[];
  document_count: number;
  error: string | null;
  video_url: string | null;
  download_url: string | null;
  poster_url: string | null;
  created_at: string | null;
}

interface ApiResponse<T> {
  status: string;
  data: T;
}

interface StartResponse {
  workflow_id: string;
  status: VideoStatus;
}

export const videoOverviewApi = {
  /**
   * Start generating a video overview (runs in the background; poll getById)
   */
  generate: async (documentIds: string[], options: VideoOptions): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>('/video-overview/generate', {
      document_ids: documentIds,
      ...options,
      // user_id and organization_id are extracted from JWT token by backend
    });
    return response.data.data;
  },

  /**
   * Generate a new video with the same documents and settings as an existing one
   */
  regenerate: async (workflowId: string): Promise<StartResponse> => {
    const response = await apiClient.post<ApiResponse<StartResponse>>(`/video-overview/${workflowId}/regenerate`);
    return response.data.data;
  },

  /**
   * List the current user's video overviews (newest first), including in-progress ones
   */
  list: async (): Promise<VideoSummary[]> => {
    const response = await apiClient.get<ApiResponse<VideoSummary[]>>('/video-overview/list');
    return response.data.data;
  },

  /**
   * Get a video's status and, once completed, its playback / download links, chapters and captions
   */
  getById: async (workflowId: string): Promise<VideoData> => {
    const response = await apiClient.get<ApiResponse<VideoData>>(`/video-overview/${workflowId}`);
    return response.data.data;
  },
};

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return '';
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
