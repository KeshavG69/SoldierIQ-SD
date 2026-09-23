import apiClient from './client';

export type QuizQuestionCount = 'fewer' | 'standard' | 'more';
export type QuizDifficulty = 'easy' | 'medium' | 'hard';

export interface QuizOptions {
  question_count: QuizQuestionCount;
  difficulty: QuizDifficulty;
  topic?: string;
}

export interface QuizAnswerOption {
  text: string;
  is_correct: boolean;
  rationale: string;
}

export interface QuizQuestion {
  question: string;
  options: QuizAnswerOption[];
  hint: string;
  source?: string | null;
  evidence?: string | null;
}

export interface QuizSettings {
  question_count?: QuizQuestionCount;
  difficulty?: QuizDifficulty;
  topic?: string | null;
}

export interface QuizData {
  title: string;
  questions: QuizQuestion[];
  workflow_id: string;
  question_count?: number;
  document_count?: number;
  settings?: QuizSettings;
}

export interface QuizSummary {
  workflow_id: string;
  title: string;
  question_count: number;
  document_count: number;
  settings: QuizSettings;
  created_at: string | null;
}

interface ApiResponse<T> {
  status: string;
  data: T;
}

export const quizApi = {
  /**
   * Generate a multiple-choice quiz from documents
   */
  generate: async (documentIds: string[], options: QuizOptions): Promise<QuizData> => {
    const response = await apiClient.post<ApiResponse<QuizData>>('/quiz/generate', {
      document_ids: documentIds,
      ...options,
      // user_id and organization_id are extracted from JWT token by backend
    });
    return response.data.data;
  },

  /**
   * List the current user's saved quizzes (newest first)
   */
  list: async (): Promise<QuizSummary[]> => {
    const response = await apiClient.get<ApiResponse<QuizSummary[]>>('/quiz/list');
    return response.data.data;
  },

  /**
   * Get a saved quiz by ID
   */
  getById: async (workflowId: string): Promise<QuizData> => {
    const response = await apiClient.get<ApiResponse<QuizData>>(`/quiz/${workflowId}`);
    return response.data.data;
  },
};
