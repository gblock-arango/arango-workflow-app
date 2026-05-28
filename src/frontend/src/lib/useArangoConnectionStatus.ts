"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api-client";

export type ArangoConnectionState = "loading" | "connected" | "error";

interface HealthStatus {
  status?: string;
  database?: string;
  gateway?: string;
  detail?: string;
  probe?: {
    status?: string;
    details?: {
      latency_ms?: number;
      response_preview?: string;
    };
  };
  registry?: {
    status?: string;
    cluster_name?: string;
  };
}

function detailFromGatewayStartupJson(data: HealthStatus): string | null {
  const probeOk = data.probe?.status === "ok";
  const registryOk = data.registry?.status === "ok";
  if (!probeOk || !registryOk) return null;
  const parts: string[] = [];
  const preview = data.probe?.details?.response_preview;
  if (preview) {
    try {
      const parsed = JSON.parse(preview) as { version?: string };
      if (parsed.version) parts.push(`Arango ${parsed.version}`);
    } catch {
      /* ignore */
    }
  }
  const cluster = data.registry?.cluster_name;
  if (cluster) parts.push(cluster);
  const latency = data.probe?.details?.latency_ms;
  if (latency != null) parts.push(`${latency}ms`);
  return parts.length > 0 ? parts.join(" · ") : "Connected";
}

function parseReadyResponse(data: HealthStatus): {
  health: ArangoConnectionState;
  detail: string;
} {
  const gatewayDetail = detailFromGatewayStartupJson(data);
  if (gatewayDetail) {
    return { health: "connected", detail: gatewayDetail };
  }
  if (data.status === "ready") {
    const detail =
      (typeof data.detail === "string" && data.detail.trim()) ||
      [data.database, data.gateway].filter(Boolean).join(" · ") ||
      "connected";
    return { health: "connected", detail };
  }
  if (data.status === "not_ready") {
    const detail =
      (typeof data.detail === "string" && data.detail.trim()) ||
      [data.database, data.gateway].filter(Boolean).join(" · ") ||
      "Database not ready";
    return { health: "error", detail };
  }
  const fallback =
    (typeof data.detail === "string" && data.detail.trim()) ||
    [data.database, data.gateway].filter(Boolean).join(" · ") ||
    "Database not ready";
  return { health: "error", detail: fallback };
}

interface CachedStatus {
  health: "connected";
  detail: string;
  at: number;
}

const CACHE_KEY = "aoe_arango_ready_v4";
/** Client timeout for ``GET /ready`` (server should answer from cache in under 1s). */
export const ARANGO_READY_FETCH_TIMEOUT_MS = 12_000;
/** Poll server cache while on the home page (no gateway ``refresh=true``). */
export const ARANGO_READY_REFRESH_MS = 60_000;
/** Occasional deep refresh (gateway re-probes Arango). */
export const ARANGO_READY_DEEP_REFRESH_MS = 300_000;
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

async function fetchReady(
  signal: AbortSignal,
  refresh: boolean,
): Promise<{
  health: ArangoConnectionState;
  detail: string;
}> {
  const path = refresh ? "/ready?refresh=true" : "/ready";
  const res = await apiFetch(path, { signal }, ARANGO_READY_FETCH_TIMEOUT_MS);
  const data = (await res.json().catch(() => ({}))) as HealthStatus;
  if (!res.ok) {
    const hint =
      typeof data.detail === "string"
        ? data.detail
        : typeof data.database === "string"
          ? data.database
          : `HTTP ${res.status}`;
    if (res.status === 500 && !data.detail && !data.database) {
      throw new Error(
        "API unreachable. Start the backend (make backend) and ensure BACKEND_PROXY_URL matches.",
      );
    }
    throw new Error(hint);
  }
  return parseReadyResponse(data);
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

  const runCheck = useCallback(async (opts: { silent: boolean; refresh: boolean }) => {
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => controller.abort(),
      ARANGO_READY_FETCH_TIMEOUT_MS,
    );

    if (!opts.silent && !readConnectedCache()) {
      setHealth("loading");
    }

    try {
      const result = await fetchReady(controller.signal, opts.refresh);
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
    void runCheck({ silent: Boolean(readConnectedCache()), refresh: false });
    const pollId = window.setInterval(
      () => void runCheck({ silent: true, refresh: false }),
      ARANGO_READY_REFRESH_MS,
    );
    const deepId = window.setInterval(
      () => void runCheck({ silent: true, refresh: true }),
      ARANGO_READY_DEEP_REFRESH_MS,
    );
    return () => {
      window.clearInterval(pollId);
      window.clearInterval(deepId);
    };
  }, [runCheck]);

  return { health, healthDetail };
}
