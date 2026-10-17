/**
 * Voice dictation API — POST /api/voice/transcribe (Deepgram Nova-3 via
 * OpenRouter on the backend). Used by lib/voice/liveDictation.ts.
 */
import apiClient from "./client";

export const voiceApi = {
  transcribe: async (audio: Blob, format: string = "wav", language?: string): Promise<string> => {
    const form = new FormData();
    form.append("audio", audio, `segment.${format}`);
    form.append("audio_format", format);
    if (language) form.append("language", language);
    const res = await apiClient.post<{ text: string }>("/voice/transcribe", form, {
      // Let the browser set the multipart boundary.
      headers: { "Content-Type": undefined as unknown as string },
    });
    return res.data.text || "";
  },
};
