import { useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '@/lib/api/documents';
import { Document } from '@/types';
import { documentKeys } from './useDocuments';

interface DeleteDocumentParams {
  docId: string;
  organizationId: string;
}

/**
 * Mutation for deleting a single document.
 * Optimistically removes the document from the cache, then invalidates on settle.
 */
export function useDeleteDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ docId }: DeleteDocumentParams) =>
      documentsApi.deleteDocument(docId),

    onMutate: async ({ docId, organizationId }) => {
      await queryClient.cancelQueries({
        queryKey: documentKeys.list(organizationId),
      });

      const previousDocs = queryClient.getQueryData<Document[]>(
        documentKeys.list(organizationId)
      );

      // Optimistically remove the document from cache
      queryClient.setQueryData<Document[]>(
        documentKeys.list(organizationId),
        (old) => (old ?? []).filter((doc) => doc.id !== docId)
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
      queryClient.invalidateQueries({
        queryKey: documentKeys.knowledgeBases(variables.organizationId),
      });
    },
  });
}

interface DeleteKnowledgeBaseParams {
  folderName: string;
  organizationId: string;
}

/**
 * Mutation for deleting a knowledge base (folder) and all its documents.
 * Invalidates both documents and knowledge bases queries on settle.
 */
export function useDeleteKnowledgeBase() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ folderName }: DeleteKnowledgeBaseParams) =>
      documentsApi.deleteFolder(folderName),

    onMutate: async ({ folderName, organizationId }) => {
      await queryClient.cancelQueries({
        queryKey: documentKeys.list(organizationId),
      });
      await queryClient.cancelQueries({
        queryKey: documentKeys.knowledgeBases(organizationId),
      });

      const previousDocs = queryClient.getQueryData<Document[]>(
        documentKeys.list(organizationId)
      );

      // Optimistically remove all documents belonging to this folder
      queryClient.setQueryData<Document[]>(
        documentKeys.list(organizationId),
        (old) => (old ?? []).filter((doc) => doc.folder_name !== folderName)
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
      queryClient.invalidateQueries({
        queryKey: documentKeys.knowledgeBases(variables.organizationId),
      });
    },
  });
}
