import { useEffect, RefObject } from "react";

/**
 * Hook that auto-resizes a textarea element to fit its content.
 * Resets height to "auto" first to handle shrinking, then sets to scrollHeight.
 */
export function useAutoResize(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string
) {
  useEffect(() => {
    if (ref.current) {
      ref.current.style.height = "auto";
      ref.current.style.height = `${ref.current.scrollHeight}px`;
    }
  }, [ref, value]);
}
