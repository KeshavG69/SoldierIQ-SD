import { useMutation, useQueryClient } from '@tanstack/react-query';
import { documentsApi } from '@/lib/api/documents';
import { Document } from '@/types';
import { documentKeys } from './useDocuments';

interface UploadDocumentParams {
  files: File[];
  folderName: string;
  organizationId: string;
}

/**
 * Mutation for uploading documents.
 * Performs an optimistic update by inserting placeholder documents into the cache,
 * then invalidates the documents and knowledge bases queries on success.
 */
export function useUploadDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ files, folderName }: UploadDocumentParams) =>
      documentsApi.uploadDocuments(files, folderName),

    onMutate: async ({ files, folderName, organizationId }) => {
      // Cancel in-flight queries so they don't overwrite our optimistic update
      await queryClient.cancelQueries({
        queryKey: documentKeys.list(organizationId),
      });

      // Snapshot current cache
      const previousDocs = queryClient.getQueryData<Document[]>(
        documentKeys.list(organizationId)
      );

      // Build placeholder documents
      const placeholders: Document[] = files.map((file, index) => ({
        id: `temp_${Date.now()}_${index}`,
        file_name: file.name,
        folder_name: folderName,
        user_id: '',
        organization_id: organizationId,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        status: 'processing' as const,
        processing_stage: 'uploading',
        processing_stage_description: 'Uploading file to server...',
      }));

      // Optimistically prepend placeholders
      queryClient.setQueryData<Document[]>(
        documentKeys.list(organizationId),
        (old) => [...placeholders, ...(old ?? [])]
      );

      return { previousDocs, organizationId };
    },

    onError: (_err, _vars, context) => {
      // Roll back to the previous cache state
      if (context?.previousDocs !== undefined) {
        queryClient.setQueryData(
          documentKeys.list(context.organizationId),
          context.previousDocs
        );
      }
    },

    onSettled: (_data, _error, variables) => {
      // Always refetch to get the real server state
      queryClient.invalidateQueries({
        queryKey: documentKeys.list(variables.organizationId),
      });
      queryClient.invalidateQueries({
        queryKey: documentKeys.knowledgeBases(variables.organizationId),
      });
    },
  });
}
