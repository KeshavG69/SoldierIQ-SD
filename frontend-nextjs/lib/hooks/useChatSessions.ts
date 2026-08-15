import { useQuery } from '@tanstack/react-query';
import { chatSessionsApi, ChatSession } from '@/lib/api/documents';

export const chatSessionKeys = {
  all: ['chatSessions'] as const,
  list: (userId?: string) => [...chatSessionKeys.all, 'list', userId] as const,
  detail: (sessionId: string) => [...chatSessionKeys.all, 'detail', sessionId] as const,
};

/**
 * Fetches the list of chat sessions for a user.
 */
export function useChatSessions(userId?: string) {
  return useQuery<ChatSession[]>({
    queryKey: chatSessionKeys.list(userId),
    queryFn: () => chatSessionsApi.listSessions(),
    enabled: !!userId,
  });
}
