// Uploads a file straight to iDrive via S3 multipart upload — the backend
// never sees the bytes. Splitting into parts (instead of one big PUT) means
// a network hiccup only costs re-sending the ONE part that failed, not the
// whole file. Critical for large videos: a single unresumable PUT of a
// multi-hundred-MB file was silently stalling forever on any interruption.

import { documentsApi } from "@/lib/api/documents";

const MAX_RETRIES_PER_PART = 3;
const RETRY_BASE_DELAY_MS = 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function uploadPartWithRetry(url: string, blob: Blob, partNumber: number): Promise<string> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_RETRIES_PER_PART; attempt++) {
    try {
      const res = await fetch(url, { method: "PUT", body: blob });
      if (!res.ok) {
        throw new Error(`Part ${partNumber} upload failed (HTTP ${res.status})`);
      }
      // S3's CompleteMultipartUpload needs the exact ETag S3 assigned to
      // this part — it's only available from this response's header.
      const etag = res.headers.get("ETag") || res.headers.get("etag");
      if (!etag) {
        throw new Error(`Part ${partNumber} uploaded but no ETag was returned`);
      }
      return etag;
    } catch (e) {
      lastError = e;
      if (attempt < MAX_RETRIES_PER_PART) {
        await sleep(RETRY_BASE_DELAY_MS * attempt); // simple linear backoff
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error(`Part ${partNumber} failed after ${MAX_RETRIES_PER_PART} attempts`);
}

export interface MultipartUploadResult {
  document_id: string;
}

/**
 * Uploads one file via multipart, one part at a time (sequential — keeps
 * memory/network usage predictable and progress easy to reason about).
 * Retries each part individually before giving up; on unrecoverable
 * failure, aborts the S3 session server-side so the document isn't left
 * stuck on "processing" forever.
 */
export async function uploadFileMultipart(
  file: File,
  folderName: string,
  onPartProgress?: (completedParts: number, totalParts: number) => void
): Promise<MultipartUploadResult> {
  const presigned = await documentsApi.presignMultipartUpload(
    file.name,
    folderName,
    file.type,
    file.size
  );

  const parts: { part_number: number; etag: string }[] = [];
  try {
    for (const { part_number, url } of presigned.part_urls) {
      const start = (part_number - 1) * presigned.part_size_bytes;
      const end = Math.min(start + presigned.part_size_bytes, file.size);
      const blob = file.slice(start, end);

      const etag = await uploadPartWithRetry(url, blob, part_number);
      parts.push({ part_number, etag });
      onPartProgress?.(parts.length, presigned.total_parts);
    }
  } catch (e) {
    // Best-effort cleanup — swallow abort errors so the ORIGINAL failure
    // is what the caller sees, not a masking cleanup error.
    documentsApi
      .abortMultipartUpload({
        document_id: presigned.document_id,
        file_key: presigned.file_key,
        upload_id: presigned.upload_id,
      })
      .catch(() => {});
    throw e;
  }

  await documentsApi.completeMultipartUpload({
    document_id: presigned.document_id,
    file_key: presigned.file_key,
    upload_id: presigned.upload_id,
    filename: file.name,
    folder_name: folderName,
    content_type: file.type,
    file_size_mb: file.size / (1024 * 1024),
    parts,
  });

  return { document_id: presigned.document_id };
}
