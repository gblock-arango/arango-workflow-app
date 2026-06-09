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

/** Drop probe latency segments like ``258ms`` from display detail. */
export function stripLatencyFromDetail(detail: string): string {
  const parts = detail
    .split(" · ")
    .map((p) => p.trim())
    .filter((p) => p.length > 0 && !/^\d+ms$/i.test(p));
  return parts.join(" · ");
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
  return parts.length > 0 ? parts.join(" · ") : "Connected";
}

function notReadyDetail(data: HealthStatus): string {
  const mapped =
    (typeof data.gateway === "string" && data.gateway.trim()) ||
    (typeof data.detail === "string" && data.detail.trim()) ||
    (typeof data.database === "string" && data.database.trim()) ||
    "";
  if (mapped && !/^probe=error,\s*registry=error$/i.test(mapped)) {
    return mapped;
  }
  const parts: string[] = [];
  const probe = data.probe;
  const registry = data.registry;
  if (probe?.status && probe.status !== "ok") {
    const probeErr =
      (probe as { error?: string }).error ||
      probe.details?.response_preview ||
      probe.status;
    parts.push(`probe: ${probeErr}`);
  }
  if (registry?.status && registry.status !== "ok") {
    const regErr =
      (registry as { error?: string; message?: string }).error ||
      (registry as { message?: string }).message ||
      registry.status;
    parts.push(`registry: ${regErr}`);
  }
  return parts.join(" · ") || mapped || "Database not ready";
}

function parseReadyResponse(data: HealthStatus): {
  health: ArangoConnectionState;
  detail: string;
} {
  // Trust mapped ``status`` first — nested probe/registry may be absent or stale.
  if (data.status === "ready") {
    const gatewayDetail = detailFromGatewayStartupJson(data);
    const detail = stripLatencyFromDetail(
      gatewayDetail ||
        (typeof data.detail === "string" && data.detail.trim()) ||
        [data.database, data.gateway].filter(Boolean).join(" · ") ||
        "connected",
    );
    return { health: "connected", detail: detail || "Connected" };
  }
  if (data.status === "not_ready") {
    return { health: "error", detail: notReadyDetail(data) };
  }
  const gatewayDetail = detailFromGatewayStartupJson(data);
  if (gatewayDetail) {
    return {
      health: "connected",
      detail: stripLatencyFromDetail(gatewayDetail),
    };
  }
  return { health: "error", detail: notReadyDetail(data) };
}

interface CachedStatus {
  health: "connected";
  detail: string;
  at: number;
}

const CACHE_KEYS = ["aoe_arango_ready_v5", "aoe_arango_ready_v4"] as const;
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
  for (const key of CACHE_KEYS) {
    try {
      const raw = sessionStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as CachedStatus;
      if (parsed.health !== "connected") continue;
      if (Date.now() - parsed.at > CONNECTED_CACHE_MAX_AGE_MS) continue;
      return {
        ...parsed,
        detail: stripLatencyFromDetail(parsed.detail),
      };
    } catch {
      continue;
    }
  }
  return null;
}

function writeConnectedCache(detail: string): void {
  if (typeof window === "undefined") return;
  try {
    const entry = JSON.stringify({
      health: "connected",
      detail: stripLatencyFromDetail(detail),
      at: Date.now(),
    } satisfies CachedStatus);
    for (const key of CACHE_KEYS) {
      sessionStorage.setItem(key, entry);
    }
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
          prev ? `${stripLatencyFromDetail(prev)} · recheck pending` : message,
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
