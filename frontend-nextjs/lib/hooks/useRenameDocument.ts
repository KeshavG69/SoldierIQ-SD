import { useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '@/lib/api/documents';
import { Document } from '@/types';
import { documentKeys } from './useDocuments';

interface RenameDocumentParams {
  docId: string;
  newFileName: string;
  organizationId: string;
}

/**
 * Mutation for renaming a document's display name.
 * Optimistically renames it in the cache so the sidebar updates instantly,
 * then reconciles with the server's sanitized name on settle (the backend
 * strips unsafe characters and re-appends the original extension).
 */
export function useRenameDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ docId, newFileName }: RenameDocumentParams) =>
      documentsApi.renameDocument(docId, newFileName),

    onMutate: async ({ docId, newFileName, organizationId }) => {
      await queryClient.cancelQueries({
        queryKey: documentKeys.list(organizationId),
      });

      const previousDocs = queryClient.getQueryData<Document[]>(
        documentKeys.list(organizationId)
      );

      queryClient.setQueryData<Document[]>(
        documentKeys.list(organizationId),
        (old) =>
          (old ?? []).map((doc) =>
            doc.id === docId ? { ...doc, file_name: newFileName } : doc
          )
      );

      return { previousDocs, organizationId };
    },

    onError: (_err, _vars, context) => {
      if (context?.previousDocs !== undefined) {
        queryClient.setQueryData(
          documentKeys.list(context.organizationId),
          context.previousDocs
        );
      }
    },

    onSettled: (_data, _error, variables) => {
      queryClient.invalidateQueries({
        queryKey: documentKeys.list(variables.organizationId),
      });
    },
  });
}
