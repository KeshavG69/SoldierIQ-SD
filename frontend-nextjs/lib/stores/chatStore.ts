import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { ChatMessage, SourceReference, KnowledgeGraph, ComposioAuthInfo, ToolCallStep } from '@/types';

const generateId = () => `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

export interface DocumentSource extends SourceReference {
  text: string;
  score: number;
  folder_name: string;
  file_key: string;
  // Video-specific fields (optional)
  video_id?: string;
  video_name?: string;
  clip_start?: number;
  clip_end?: number;
  scene_id?: string;
  key_frame_timestamp?: number;
  keyframe_file_key?: string;
}

// TAK credentials for chat integration
export interface TAKCredentials {
  tak_host: string;
  tak_port: number;
  tak_username: string;
  tak_password: string;
  agent_callsign: string;
}

interface ChatState {
  messages: ChatMessage[];
  sessionId: string;
  isLoading: boolean;
  isLoadingSession: boolean;
  inputMessage: string;
  selectedModel: string;
  takCredentials: TAKCredentials | null;
  takEnabled: boolean;

  // Actions
  setInputMessage: (message: string) => void;
  setSelectedModel: (model: string) => void;
  addMessage: (message: ChatMessage) => void;
  updateLastMessage: (
    content: string,
    sources?: DocumentSource[],
    graph?: KnowledgeGraph
  ) => void;
  setLastMessageComposioAuth: (info: ComposioAuthInfo) => void;
  upsertLastMessageToolCall: (step: Partial<ToolCallStep> & { id: string }) => void;
  endStreaming: () => void;
  setLoading: (loading: boolean) => void;
  setLoadingSession: (loading: boolean) => void;
  clearChat: () => void;
  startNewSession: () => void;
  loadSession: (sessionId: string, messages: ChatMessage[]) => void;
  setTAKCredentials: (credentials: TAKCredentials | null) => void;
  setTAKEnabled: (enabled: boolean) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
  messages: [],
  sessionId: generateId(),
  isLoading: false,
  isLoadingSession: false,
  inputMessage: '',
  selectedModel: 'anthropic/claude-sonnet-5.5', // Default model
  takCredentials: null,
  takEnabled: false,

  setInputMessage: (message) => set({ inputMessage: message }),

  setSelectedModel: (model) => set({ selectedModel: model }),

  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),

  updateLastMessage: (content, sources, graph) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        messages[messages.length - 1] = {
          ...messages[messages.length - 1],
          content,
          ...(sources && { sources }),
          ...(graph && { graph }),
        };
      }
      return { messages };
    }),

  setLastMessageComposioAuth: (info) =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        messages[messages.length - 1] = { ...messages[messages.length - 1], composioAuth: info };
      }
      return { messages };
    }),

  upsertLastMessageToolCall: (step) =>
    set((state) => {
      const messages = [...state.messages];
      const last = messages[messages.length - 1];
      if (!last) return { messages };
      const calls = [...(last.toolCalls || [])];
      const i = calls.findIndex((c) => c.id === step.id);
      if (i >= 0) {
        const merged = { ...calls[i], ...step };
        // Fall back to client-side timing when the backend sent no duration.
        if (merged.status !== "running" && merged.duration == null && merged.startedAt) {
          merged.duration = (Date.now() - merged.startedAt) / 1000;
        }
        calls[i] = merged;
      }
      else calls.push(step as ToolCallStep);
      messages[messages.length - 1] = { ...last, toolCalls: calls };
      return { messages };
    }),

  endStreaming: () =>
    set((state) => {
      const messages = [...state.messages];
      if (messages.length > 0) {
        const last = messages[messages.length - 1];
        messages[messages.length - 1] = {
          ...last,
          isStreaming: false,
          // A step still "running" when the stream ends never finished.
          ...(last.toolCalls && {
            toolCalls: last.toolCalls.map((c) =>
              c.status === "running" ? { ...c, status: "error" as const } : c
            ),
          }),
        };
      }
      return { messages };
    }),

  setLoading: (loading) => set({ isLoading: loading }),

  setLoadingSession: (loading) => set({ isLoadingSession: loading }),

  clearChat: () => set({ messages: [] }),

  startNewSession: () => set({ messages: [], sessionId: generateId() }),

  loadSession: (sessionId, messages) => set({ sessionId, messages }),

  setTAKCredentials: (credentials) => set({ takCredentials: credentials }),

  setTAKEnabled: (enabled) => set({ takEnabled: enabled }),
    }),
    {
      // Keep the current conversation (and chosen model) across reloads so the
      // session history survives a refresh without re-fetching from the backend.
      name: 'soldieriq-chat-session',
      storage: createJSONStorage(() => localStorage),
      version: 2,
      // v2: Sonnet 4.5 was replaced by Sonnet 5.5 — move saved selections over.
      migrate: (persisted: any, version) => {
        if (version < 2 && persisted?.selectedModel === 'anthropic/claude-sonnet-4.5') {
          persisted.selectedModel = 'anthropic/claude-sonnet-5.5';
        }
        return persisted;
      },
      // Persist only the conversation + model. NOT transient flags (loading,
      // input draft) and NOT takCredentials (contains a password).
      partialize: (state) => ({
        messages: state.messages,
        sessionId: state.sessionId,
        selectedModel: state.selectedModel,
      }),
    }
  )
);
