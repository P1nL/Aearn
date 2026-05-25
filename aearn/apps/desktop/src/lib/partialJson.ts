import { parse, Allow, PartialJSON, MalformedJSON } from "partial-json";

/**
 * Parse a partial JSON buffer into the longest valid prefix.
 *
 * Returns `null` when the buffer cannot be parsed yet (e.g. mid-key or empty).
 * `Allow.ALL` lets the parser tolerate trailing strings, arrays, objects,
 * numbers, booleans, and nulls. If the buffer is malformed (not just partial),
 * we still return `null` so the caller can wait for more data.
 */
export function parsePartial(buffer: string): unknown {
  if (!buffer || !buffer.trim()) {
    return null;
  }
  try {
    return parse(buffer, Allow.ALL);
  } catch (error) {
    if (error instanceof PartialJSON || error instanceof MalformedJSON) {
      return null;
    }
    return null;
  }
}
