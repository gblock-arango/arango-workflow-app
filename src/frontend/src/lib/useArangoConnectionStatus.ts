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
  health: "connected";
  detail: string;
  at: number;
}

const CACHE_KEY = "aoe_arango_ready_v1";
/** Browser fetch timeout for ``GET /ready`` (one gateway version probe; server caches ~45s). */
export const ARANGO_READY_FETCH_TIMEOUT_MS = 15_000;
/** Background re-check while staying on the home page (does not flash yellow). */
export const ARANGO_READY_REFRESH_MS = 60_000;
/** Reuse a successful connected status on remount for this long. */
const CONNECTED_CACHE_MAX_AGE_MS = 120_000;

function readConnectedCache(): CachedStatus | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedStatus;
    if (parsed.health !== "connected") return null;
    if (Date.now() - parsed.at > CONNECTED_CACHE_MAX_AGE_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeConnectedCache(detail: string): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ health: "connected", detail, at: Date.now() } satisfies CachedStatus),
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
 * Only caches successful ``connected`` state (never caches errors/timeouts), so
 * navigating back to home does not flash offline from a stale failed probe.
 */
export function useArangoConnectionStatus(): {
  health: ArangoConnectionState;
  healthDetail: string;
} {
  const connectedCache = readConnectedCache();
  const [health, setHealth] = useState<ArangoConnectionState>(() =>
    connectedCache ? "connected" : "loading",
  );
  const [healthDetail, setHealthDetail] = useState(
    () => connectedCache?.detail ?? "",
  );
  const healthRef = useRef(health);
  healthRef.current = health;

  const runCheck = useCallback(async (opts: { silent: boolean }) => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => controller.abort(),
      ARANGO_READY_FETCH_TIMEOUT_MS,
    );

    if (!opts.silent && !readConnectedCache()) {
      setHealth("loading");
    }

    try {
      const result = await fetchReady(controller.signal);
      setHealth(result.health);
      setHealthDetail(result.detail);
      if (result.health === "connected") {
        writeConnectedCache(result.detail);
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error && err.name === "AbortError"
            ? "Connection check timed out"
            : String(err);

      if (opts.silent && healthRef.current === "connected") {
        setHealthDetail((prev) =>
          prev ? `${prev} · recheck pending` : message,
        );
        return;
      }

      setHealth("error");
      setHealthDetail(message);
    } finally {
      window.clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    void runCheck({ silent: Boolean(readConnectedCache()) });
    const id = window.setInterval(
      () => void runCheck({ silent: true }),
      ARANGO_READY_REFRESH_MS,
    );
    return () => window.clearInterval(id);
  }, [runCheck]);

  return { health, healthDetail };
}
