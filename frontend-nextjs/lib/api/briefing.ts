import apiClient from './client';

export interface BriefingContext {
  location: string | null;
  location_source: string | null;
  weather: string | null;
  part_of_day: string;
  selected_documents: number;
}

export interface Briefing {
  greeting: string;
  suggestions: string[];
  context: BriefingContext;
}

export const briefingApi = {
  // The agent's opening message after sign-in (selected docs + location + local time).
  get: async (signals: { latitude?: number; longitude?: number; timezone?: string }): Promise<Briefing> => {
    const res = await apiClient.post<Briefing>('/chat/briefing', signals, { timeout: 45000 });
    return res.data;
  },
};
