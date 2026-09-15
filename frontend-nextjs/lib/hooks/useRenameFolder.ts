import { useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '@/lib/api/documents';
import { documentKeys } from './useDocuments';

interface RenameFolderParams {
  folderName: string;
  newFolderName: string;
  organizationId: string;
}

/**
 * Mutation for renaming a folder (knowledge base).
 *
 * Deliberately NOT optimistic: the folder name is the folder row's React key,
 * so rewriting it in the cache immediately would unmount the inline editor
 * (and its error state) mid-request. Instead we let the editor stay mounted
 * through the await and reconcile from the server on settle — on success the
 * refetch shows the new name, on failure the editor keeps the typed value and
 * surfaces the error.
 */
export function useRenameFolder() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ folderName, newFolderName }: RenameFolderParams) =>
      documentsApi.renameFolder(folderName, newFolderName),

    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({
        queryKey: documentKeys.list(variables.organizationId),
      });
      queryClient.invalidateQueries({
        queryKey: documentKeys.knowledgeBases(variables.organizationId),
      });
    },
  });
}
