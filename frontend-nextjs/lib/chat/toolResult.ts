/**
 * Short, human-readable preview of a tool result for the step timeline.
 * Kept small (it's persisted with the chat in localStorage).
 */

const MAX_PREVIEW = 1500;

function clip(text: string): string {
  return text.length > MAX_PREVIEW ? `${text.slice(0, MAX_PREVIEW)}…` : text;
}

export function summarizeToolResult(toolName: string | undefined, result: unknown): string | undefined {
  if (result == null || result === "") return undefined;
  let parsed: any = result;
  if (typeof result === "string") {
    try {
      parsed = JSON.parse(result);
    } catch {
      return clip(result);
    }
  }

  // Knowledge-base / graph search: [{ chunks, anchors, triples, ... }]
  if (toolName === "search_knowledge_base") {
    const payload = Array.isArray(parsed) ? parsed[0] : parsed;
    if (payload && Array.isArray(payload.chunks)) {
      const parts = [`${payload.chunks.length} passage${payload.chunks.length === 1 ? "" : "s"} found`];
      if (payload.anchors?.length) parts.push(`${payload.anchors.length} entities`);
      if (payload.triples?.length) parts.push(`${payload.triples.length} relations`);
      return parts.join(" · ");
    }
  }

  // Composio setup tools report a sentence in `message`.
  if (parsed && typeof parsed === "object" && typeof parsed.message === "string" && !("data" in parsed)) {
    return clip(parsed.message);
  }

  // Composio actions: { successful, data, error }
  if (parsed && typeof parsed === "object" && "successful" in parsed) {
    if (!parsed.successful) return clip(`Error: ${parsed.error || "the action failed"}`);
    return clip(JSON.stringify(parsed.data ?? {}, null, 2));
  }

  return clip(typeof parsed === "string" ? parsed : JSON.stringify(parsed, null, 2));
}
