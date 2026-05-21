"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api-client";

export type ArangoConnectionState = "loading" | "connected" | "error";

interface HealthStatus {
  status: string;
  database?: string;
  gateway?: string;
  detail?: string;
}

interface CachedStatus {
  health: ArangoConnectionState;
  detail: string;
  at: number;
}

const CACHE_KEY = "aoe_arango_ready_v1";
/** Browser fetch timeout for ``GET /ready`` (gateway probe + Arango version). */
export const ARANGO_READY_FETCH_TIMEOUT_MS = 25_000;
/** Background re-check while staying on the home page (does not flash yellow). */
export const ARANGO_READY_REFRESH_MS = 60_000;
/** Reuse cached status on remount/navigation for this long. */
const CACHE_MAX_AGE_MS = 120_000;

function readCache(): CachedStatus | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedStatus;
    if (Date.now() - parsed.at > CACHE_MAX_AGE_MS) return null;
    if (parsed.health !== "connected" && parsed.health !== "error") return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeCache(health: ArangoConnectionState, detail: string): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ health, detail, at: Date.now() } satisfies CachedStatus),
    );
  } catch {
    /* quota / private mode */
  }
}

async function fetchReady(signal: AbortSignal): Promise<{
  health: ArangoConnectionState;
  detail: string;
}> {
  const res = await apiFetch("/ready", { signal });
  const data = (await res.json().catch(() => ({}))) as HealthStatus;
  if (!res.ok) {
    const hint =
      typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
    if (res.status === 500 && !data.detail) {
      throw new Error(
        "API unreachable. Start the backend (make backend) and ensure BACKEND_PROXY_URL matches.",
      );
    }
    throw new Error(hint);
  }
  if (data.status === "ready") {
    const parts = [data.gateway, data.database].filter(Boolean);
    return {
      health: "connected",
      detail: parts.join(" · ") || "connected",
    };
  }
  return {
    health: "error",
    detail: data.database || data.gateway || "Database not ready",
  };
}

/**
 * Home-page "Connection to Arango" widget.
 *
 * - Yellow only on the first check with no recent cache (not on background refresh).
 * - ``/ready`` uses a 25s client timeout; the gateway health probe uses up to 30s server-side.
 * - Re-checks every 60s without resetting to yellow when already connected.
 */
export function useArangoConnectionStatus(): {
  health: ArangoConnectionState;
  healthDetail: string;
} {
  const cached = readCache();
  const [health, setHealth] = useState<ArangoConnectionState>(
    () => cached?.health ?? "loading",
  );
  const [healthDetail, setHealthDetail] = useState(() => cached?.detail ?? "");
  const healthRef = useRef(health);
  healthRef.current = health;

  const runCheck = useCallback(async (opts: { silent: boolean }) => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => controller.abort(),
      ARANGO_READY_FETCH_TIMEOUT_MS,
    );

    if (!opts.silent && !readCache()) {
      setHealth("loading");
    }

    try {
      const result = await fetchReady(controller.signal);
      setHealth(result.health);
      setHealthDetail(result.detail);
      writeCache(result.health, result.detail);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error && err.name === "AbortError"
            ? "Connection check timed out"
            : String(err);

      if (opts.silent && healthRef.current === "connected") {
        setHealthDetail((prev) =>
          prev ? `${prev} · recheck failed` : message,
        );
        return;
      }

      setHealth("error");
      setHealthDetail(message);
      writeCache("error", message);
    } finally {
      window.clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    void runCheck({ silent: Boolean(readCache()) });
    const id = window.setInterval(
      () => void runCheck({ silent: true }),
      ARANGO_READY_REFRESH_MS,
    );
    return () => window.clearInterval(id);
  }, [runCheck]);

  return { health, healthDetail };
}
