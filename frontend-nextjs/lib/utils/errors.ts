/**
 * Normalize an API/axios error into a human-readable string.
 *
 * FastAPI returns validation errors (422) as `detail: [{type, loc, msg, input}]`
 * and other errors as `detail: "some message"`. Rendering the array/object form
 * directly in JSX throws "Objects are not valid as a React child", so every
 * user-facing catch should route through here to guarantee a string.
 */
export function getErrorMessage(err: any, fallback = "Something went wrong. Please try again."): string {
  const detail = err?.response?.data?.detail;

  if (typeof detail === "string" && detail.trim()) return detail;

  // 422 validation errors: array of { msg, loc, ... }
  if (Array.isArray(detail)) {
    const msg = detail
      .map((d) => (typeof d === "string" ? d : d?.msg))
      .filter(Boolean)
      .join("; ");
    if (msg) return msg;
  }

  // Single object with a msg field
  if (detail && typeof detail === "object" && typeof detail.msg === "string") {
    return detail.msg;
  }

  if (typeof err?.message === "string" && err.message.trim()) return err.message;

  return fallback;
}
