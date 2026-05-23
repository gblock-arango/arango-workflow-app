import { ApiError, LONG_RUNNING_API_TIMEOUT_MS } from "@/lib/api-client";

export interface OperationErrorContext {
  operation: string;
  path?: string;
  filename?: string;
  timeoutMs?: number;
}

/** Human-readable + technical detail for upload / import failure banners. */
export function formatOperationError(
  err: unknown,
  ctx: OperationErrorContext,
): string {
  const timeoutMs = ctx.timeoutMs ?? LONG_RUNNING_API_TIMEOUT_MS;
  const lines: string[] = [];

  if (err instanceof ApiError) {
    lines.push(err.message);
    if (err.body.details && Object.keys(err.body.details).length > 0) {
      lines.push(
        Object.entries(err.body.details)
          .filter(([, v]) => v != null && String(v).length > 0)
          .map(([k, v]) => `${k}: ${v}`)
          .join("; "),
      );
    }
    if (err.body.code) {
      lines.push(`code: ${err.body.code}`);
    }
    lines.push(`HTTP ${err.status}`);
  } else if (err instanceof Error) {
    const msg = err.message || err.name;
    const isAbort =
      err.name === "AbortError" ||
      err.name === "TimeoutError" ||
      /signal timed out/i.test(msg) ||
      /aborted/i.test(msg);

    if (isAbort) {
      const sec = Math.round(timeoutMs / 1000);
      lines.push(
        `The browser stopped waiting after ${sec}s (client timeout).`,
        "The workflow app may still be running migrations, copying to the UC volume, or importing into Arango.",
        "Wait 1–2 minutes, refresh Recent Documents or the Library, then retry if nothing appeared.",
      );
    } else {
      lines.push(msg);
    }
    if (err.name && !isAbort) {
      lines.push(`(${err.name})`);
    }
  } else {
    lines.push(String(err));
  }

  lines.push(`Operation: ${ctx.operation}`);
  if (ctx.path) {
    lines.push(`Volume path: ${ctx.path}`);
  }
  if (ctx.filename) {
    lines.push(`File: ${ctx.filename}`);
  }

  return lines.join("\n");
}
