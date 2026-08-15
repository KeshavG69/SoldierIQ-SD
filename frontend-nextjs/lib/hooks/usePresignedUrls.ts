import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { SourceReference } from "@/types";

/**
 * Hook that manages a cache of file_key -> presigned URL mappings.
 * Given an array of SourceReference objects, fetches presigned URLs
 * only for file_keys not already cached or in-flight.
 */
export function usePresignedUrls(sources: SourceReference[]) {
  const [urlMap, setUrlMap] = useState<Map<string, string>>(new Map());
  const fetchedKeysRef = useRef<Set<string>>(new Set());

  // Extract unique file_keys and create a stable string for dependency tracking
  const fileKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const source of sources) {
      if (source.file_key) keys.add(source.file_key);
    }
    return Array.from(keys);
  }, [sources]);

  // Stable dependency — only re-run when the set of unique keys actually changes
  const keysFingerprint = fileKeys.join("|");

  useEffect(() => {
    const keysToFetch = fileKeys.filter(
      (key) => !fetchedKeysRef.current.has(key)
    );

    if (keysToFetch.length === 0) return;

    // Mark as in-flight immediately
    keysToFetch.forEach((key) => fetchedKeysRef.current.add(key));

    let cancelled = false;

    const fetchUrls = async () => {
      const results = await Promise.all(
        keysToFetch.map(async (fileKey) => {
          try {
            const response = await fetch(
              `/api/files/presigned-url?file_key=${encodeURIComponent(fileKey)}`
            );
            if (response.ok) {
              const data = await response.json();
              return { fileKey, url: data.url as string };
            }
          } catch {
            // Allow retry on next render
            fetchedKeysRef.current.delete(fileKey);
          }
          return null;
        })
      );

      if (cancelled) return;

      setUrlMap((prev) => {
        const next = new Map(prev);
        for (const result of results) {
          if (result) next.set(result.fileKey, result.url);
        }
        return next;
      });
    };

    fetchUrls();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keysFingerprint]);

  const getUrl = useCallback(
    (fileKey: string): string | undefined => urlMap.get(fileKey),
    [urlMap]
  );

  return { urlMap, getUrl };
}
