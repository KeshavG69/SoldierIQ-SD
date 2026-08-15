import apiClient from './client';

export interface Flashcard {
  front: string;
  back: string;
}

export interface FlashcardData {
  title: string;
  cards: Flashcard[];
  workflow_id: string;
  card_count?: number;
  document_count?: number;
}

export interface FlashcardResponse {
  status: string;
  data: FlashcardData;
}

export const flashcardsApi = {
  /**
   * Generate flashcards from documents
   */
  generate: async (documentIds: string[]): Promise<FlashcardData> => {
    const response = await apiClient.post<FlashcardResponse>('/flashcards/generate', {
      document_ids: documentIds,
      // user_id and organization_id are extracted from JWT token by backend
    });
    return response.data.data;
  },
};
