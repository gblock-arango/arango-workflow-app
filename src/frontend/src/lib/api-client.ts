/**
 * Typed fetch wrapper for all AOE backend API calls.
 *
 * Handles the standard pagination envelope and error format
 * defined in PRD Section 7.8.
 */

import { getToken } from "@/lib/auth";
import { getBasePath } from "@/lib/base-path";

function isRelativeApiPath(url: string): boolean {
  return url.startsWith("/") && !url.startsWith("//");
}

/** True when the UI is served from a non-local host (Databricks Apps, staging, etc.). */
function isHostedAppOrigin(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h !== "localhost" && h !== "127.0.0.1";
}

// --- Response types -------------------------------------------------------

export interface PaginatedResponse<T> {
  data: T[];
  cursor: string | null;
  has_more: boolean;
  total_count: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

// --- Error class ----------------------------------------------------------

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Parse AOE ``{ error: { message, details } }`` or FastAPI ``detail`` from a failed fetch. */
export async function readApiErrorMessage(res: Response): Promise<string> {
  try {
    const json = (await res.json()) as {
      error?: ApiErrorBody;
      detail?: string | { msg?: string }[];
    };
    if (json.error?.message) {
      const parts = [json.error.message];
      const details = json.error.details;
      if (details && typeof details === "object") {
        const extra = Object.entries(details)
          .filter(([, v]) => v != null && String(v).length > 0)
          .map(([k, v]) => `${k}: ${v}`)
          .join("; ");
        if (extra) parts.push(extra);
      }
      return parts.join(" — ");
    }
    if (typeof json.detail === "string") {
      return json.detail;
    }
    if (Array.isArray(json.detail)) {
      return json.detail.map((d) => d.msg ?? JSON.stringify(d)).join("; ");
    }
  } catch {
    /* ignore */
  }
  const fallback = res.statusText?.trim();
  if (fallback) {
    return `${fallback} (HTTP ${res.status})`;
  }
  return `Request failed with HTTP ${res.status}`;
}

// --- Client ---------------------------------------------------------------

/**
 * When `NEXT_PUBLIC_API_URL` is unset in the browser, the client uses same-origin
 * `/api/*` paths; `next.config.js` rewrites those to this FastAPI origin.
 * Port 8010 avoids common conflicts with other services on :8000.
 */
export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8010";

/** Default client timeout so a stuck Arango/gateway call does not freeze the UI. */
export const DEFAULT_API_TIMEOUT_MS = 45_000;

/** UC volume ingest, file upload, and ontology import acceptance (server may still run longer). */
export const LONG_RUNNING_API_TIMEOUT_MS = 300_000;

/** UC volume browse on cold app start (Files API directory walk). */
export const VOLUME_BROWSE_TIMEOUT_MS = 120_000;

/**
 * Use same-origin `/api/*` (Next.js rewrite → FastAPI) when local dev would
 * otherwise send traffic to port 8000 — commonly occupied by a non-AOE service.
 * Set NEXT_PUBLIC_API_FORCE_URL=1 to disable and honor NEXT_PUBLIC_API_URL exactly.
 */
function shouldUseSameOriginApiProxy(envUrl: string | undefined): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  if (h !== "localhost" && h !== "127.0.0.1") return false;
  if (process.env.NEXT_PUBLIC_API_FORCE_URL === "1") return false;
  if (envUrl === undefined || envUrl.trim() === "") return true;
  try {
    return new URL(envUrl).port === "8000";
  } catch {
    return false;
  }
}

/**
 * Resolved API base for HTTP ``fetch`` / relative URLs.
 *
 * - Local dev: same-origin ``/api`` proxy (empty string) when applicable.
 * - Static bundle behind ``SERVICE_URL_PATH_PREFIX``: ``origin + NEXT_PUBLIC_BASE_PATH``.
 * - Otherwise: ``NEXT_PUBLIC_API_URL`` or default dev origin.
 */
function effectiveApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  const trimmed = typeof envUrl === "string" ? envUrl.trim() : "";

  if (shouldUseSameOriginApiProxy(trimmed || undefined)) {
    return "";
  }

  const basePath = getBasePath();

  // Databricks Apps: FastAPI serves /api on the same origin; avoid defaulting to 127.0.0.1:8010.
  if (
    typeof window !== "undefined" &&
    isHostedAppOrigin() &&
    (!trimmed || isRelativeApiPath(trimmed))
  ) {
    if (basePath) {
      return resolveApiBaseUrl(`${window.location.origin}${basePath}`);
    }
    return "";
  }

  if (!trimmed && basePath && typeof window !== "undefined") {
    return resolveApiBaseUrl(`${window.location.origin}${basePath}`);
  }

  return resolveApiBaseUrl(
    trimmed.length > 0 ? trimmed : DEFAULT_BACKEND_ORIGIN,
  );
}

/**
 * Browser ``fetch`` to this app’s API (same-origin on Databricks Apps).
 * Adds auth token when present; does not set ``Content-Type`` (safe for ``FormData``).
 */
export function apiFetch(
  path: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_API_TIMEOUT_MS,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const timeoutSignal =
    !init?.signal &&
    typeof AbortSignal !== "undefined" &&
    "timeout" in AbortSignal
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
  const signal = init?.signal ?? timeoutSignal;

  return fetch(backendUrl(path), {
    ...init,
    headers,
    signal,
    credentials: init?.credentials ?? "same-origin",
  });
}

/** Same as ``apiFetch`` with a 5-minute client timeout (volume / import acceptance). */
export function apiFetchLongRunning(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  return apiFetch(path, init, LONG_RUNNING_API_TIMEOUT_MS);
}

export interface UploadProgressEvent {
  loaded: number;
  total: number;
  percent: number;
}

/**
 * POST ``FormData`` with XMLHttpRequest upload progress (``fetch`` has no upload events).
 */
export function apiUploadWithProgress(
  path: string,
  formData: FormData,
  options: {
    headers?: Record<string, string>;
    onProgress?: (event: UploadProgressEvent) => void;
    timeoutMs?: number;
  } = {},
): Promise<Response> {
  const { headers, onProgress, timeoutMs = LONG_RUNNING_API_TIMEOUT_MS } = options;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", backendUrl(path));
    xhr.timeout = timeoutMs;
    const token = getToken();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    if (headers) {
      for (const [key, value] of Object.entries(headers)) {
        xhr.setRequestHeader(key, value);
      }
    }
    xhr.upload.addEventListener("progress", (event) => {
      if (!onProgress || !event.lengthComputable || event.total <= 0) {
        return;
      }
      onProgress({
        loaded: event.loaded,
        total: event.total,
        percent: Math.round((event.loaded / event.total) * 100),
      });
    });
    xhr.onload = () => {
      resolve(
        new Response(xhr.responseText, {
          status: xhr.status,
          statusText: xhr.statusText,
        }),
      );
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.ontimeout = () => reject(new Error("Upload timed out"));
    xhr.send(formData);
  });
}

function resolveApiBaseUrl(baseUrl: string): string {
  if (typeof window === "undefined") {
    return baseUrl;
  }

  try {
    const url = new URL(baseUrl);
    const isLocalFrontendHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocalFrontendHost && url.hostname === "localhost") {
      url.hostname = "127.0.0.1";
    }

    return url.toString().replace(/\/$/, "");
  } catch {
    return baseUrl;
  }
}

/** Join base URL with an API path, avoiding duplicate `/api/v1` when base already ends with it. */
export function buildApiUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  const dup = "/api/v1";
  if (base.endsWith(dup) && p.startsWith(`${dup}/`)) {
    return `${base}${p.slice(dup.length)}`;
  }
  return `${base}${p}`;
}

class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl?: string) {
    if (baseUrl !== undefined) {
      const t = baseUrl.trim();
      if (shouldUseSameOriginApiProxy(t || undefined)) {
        this.baseUrl = "";
      } else {
        this.baseUrl = resolveApiBaseUrl(t.length > 0 ? t : DEFAULT_BACKEND_ORIGIN);
      }
      return;
    }
    this.baseUrl = effectiveApiBaseUrl();
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
    timeoutMs: number = DEFAULT_API_TIMEOUT_MS,
  ): Promise<T> {
    const url = buildApiUrl(this.baseUrl, path);
    const timeoutSignal =
      !signal &&
      typeof AbortSignal !== "undefined" &&
      "timeout" in AbortSignal
        ? AbortSignal.timeout(timeoutMs)
        : undefined;
    const mergedSignal = signal ?? timeoutSignal;

    const init: RequestInit = {
      method,
      headers: this.getHeaders(),
      signal: mergedSignal,
      credentials: "same-origin",
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }

    const res = await fetch(url, init);

    if (!res.ok) {
      let errorBody: ApiErrorBody;
      try {
        const json = await res.json();
        errorBody = json.error ?? {
          code: "UNKNOWN_ERROR",
          message: json.detail ?? res.statusText,
        };
      } catch {
        errorBody = { code: "UNKNOWN_ERROR", message: res.statusText };
      }
      throw new ApiError(res.status, errorBody);
    }

    return res.json() as Promise<T>;
  }

  async get<T>(
    path: string,
    opts?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<T> {
    return this.request<T>("GET", path, undefined, opts?.signal, opts?.timeoutMs);
  }

  async post<T>(
    path: string,
    body?: unknown,
    opts?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<T> {
    return this.request<T>("POST", path, body, opts?.signal, opts?.timeoutMs);
  }

  async put<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }): Promise<T> {
    return this.request<T>("PUT", path, body, opts?.signal);
  }

  async del(path: string, opts?: { signal?: AbortSignal }): Promise<void> {
    await this.request<void>("DELETE", path, undefined, opts?.signal);
  }
}

export const api = new ApiClient();

/**
 * Base URL prefix for browser `fetch(...)` to the API.
 *
 * Returns `""` when the Next.js same-origin rewrite should be used (the
 * default in local dev) so callers end up with relative `/api/...` paths and
 * avoid cross-origin/CORS entirely. Returns an absolute origin otherwise.
 *
 * For WebSocket URLs (which need an absolute `ws://` / `wss://`), use
 * `getApiOrigin()` instead.
 */
export function getApiBaseUrl(): string {
  return effectiveApiBaseUrl();
}

/**
 * Full URL for ``fetch`` / ``<a href>`` to this FastAPI app (``/ready``, ``/health``, ``/api/v1/...``).
 * Uses ``getApiBaseUrl()`` so paths include ``SERVICE_URL_PATH_PREFIX`` when the static bundle is deployed behind it.
 */
export function backendUrl(path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  return buildApiUrl(getApiBaseUrl(), p);
}

/**
 * Always-absolute API origin (protocol + host + port, no trailing slash).
 *
 * Use this when you need a real URL — e.g. building a WebSocket URL — rather
 * than a fetch prefix. Browser HTTP callers should prefer `getApiBaseUrl()`
 * so the Next.js rewrite handles CORS.
 *
 * If the configured ``NEXT_PUBLIC_API_URL`` is a relative path (e.g. ``/api/v1``
 * in a static-export deploy), the URL parser cannot extract an origin; we
 * fall back to ``window.location.origin`` so callers building ``ws://``/``wss://``
 * URLs still get a valid host. SSR returns ``""`` (callers handle that).
 */
export function getApiOrigin(): string {
  const direct = effectiveApiBaseUrl();
  const candidate =
    direct !== ""
      ? direct
      : (process.env.NEXT_PUBLIC_API_URL?.trim() || DEFAULT_BACKEND_ORIGIN);

  try {
    return new URL(candidate).origin;
  } catch {
    if (typeof window !== "undefined") {
      return window.location.origin;
    }
    return "";
  }
}
