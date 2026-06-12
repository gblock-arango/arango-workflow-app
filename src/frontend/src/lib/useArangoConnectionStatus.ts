"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiFetch } from "@/lib/api-client";

export type ArangoConnectionState = "loading" | "connected" | "unset" | "failed";

interface ConnectionUiPayload {
  ui_variant?: "connected" | "unset" | "failed";
  ui_message?: string;
  active_profile?: string;
  active_profile_display_name?: string;
  has_saved_profiles?: boolean;
}

interface HealthStatus {
  status?: string;
  database?: string;
  gateway?: string;
  detail?: string;
  connection?: ConnectionUiPayload;
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

export interface ArangoConnectionStatus {
  health: ArangoConnectionState;
  healthDetail: string;
  profileName: string;
  /** Arango version and cluster when connected, e.g. ``Arango 3.12.4 | local-minikube-dev``. */
  connectionMeta: string;
}

/** Drop probe latency segments like ``258ms`` from display detail. */
export function stripLatencyFromDetail(detail: string): string {
  const parts = detail
    .split(" · ")
    .map((p) => p.trim())
    .filter((p) => p.length > 0 && !/^\d+ms$/i.test(p));
  return parts.join(" · ");
}

function connectionMetaFromGatewayStartupJson(data: HealthStatus): string {
  const probeOk = data.probe?.status === "ok";
  const registryOk = data.registry?.status === "ok";
  if (!probeOk || !registryOk) return "";
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
  return parts.length > 0 ? parts.join(" | ") : "";
}

function detailFromGatewayStartupJson(data: HealthStatus): string | null {
  const meta = connectionMetaFromGatewayStartupJson(data);
  return meta ? meta.replace(/ \| /g, " · ") : null;
}

export function parseReadyResponse(data: HealthStatus): ArangoConnectionStatus {
  const connection = data.connection;

  if (data.status === "ready") {
    const profileName =
      connection?.active_profile_display_name?.trim() ||
      connection?.ui_message?.trim() ||
      (typeof data.detail === "string" ? data.detail.trim() : "") ||
      "Connected";
    const connectionMeta = connectionMetaFromGatewayStartupJson(data);
    const extra = detailFromGatewayStartupJson(data);
    const healthDetail =
      extra && !extra.includes(profileName)
        ? stripLatencyFromDetail(`${profileName} · ${extra}`)
        : stripLatencyFromDetail(extra || profileName);
    return {
      health: "connected",
      profileName,
      healthDetail,
      connectionMeta,
    };
  }

  if (connection?.ui_variant === "unset") {
    return {
      health: "unset",
      profileName: "",
      healthDetail: connection.ui_message || "Click to Connect",
      connectionMeta: "",
    };
  }

  if (connection?.ui_variant === "failed" || data.status === "not_ready") {
    const profileName = connection?.active_profile_display_name?.trim() || "";
    return {
      health: "failed",
      profileName,
      healthDetail: connection?.ui_message || "Connection Failed",
      connectionMeta: "",
    };
  }

  return {
    health: "unset",
    profileName: "",
    healthDetail: "Click to Connect",
    connectionMeta: "",
  };
}

interface CachedStatus {
  health: "connected";
  detail: string;
  profileName: string;
  connectionMeta: string;
  at: number;
}

const CACHE_KEYS = ["aoe_arango_ready_v6", "aoe_arango_ready_v5"] as const;
export const ARANGO_READY_FETCH_TIMEOUT_MS = 12_000;
export const ARANGO_READY_REFRESH_MS = 60_000;
export const ARANGO_READY_DEEP_REFRESH_MS = 300_000;
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
        connectionMeta: parsed.connectionMeta ?? "",
      };
    } catch {
      continue;
    }
  }
  return null;
}

function writeConnectedCache(
  detail: string,
  profileName: string,
  connectionMeta: string,
): void {
  if (typeof window === "undefined") return;
  try {
    const entry = JSON.stringify({
      health: "connected",
      detail: stripLatencyFromDetail(detail),
      profileName,
      connectionMeta,
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
): Promise<ArangoConnectionStatus> {
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
 * Home-page and Connection page Arango status widget.
 *
 * Never surfaces raw probe/registry diagnostics — only user-facing connection copy.
 */
export function useArangoConnectionStatus(): ArangoConnectionStatus & {
  refresh: (opts?: { force?: boolean }) => void;
} {
  const connectedCache = readConnectedCache();
  const [health, setHealth] = useState<ArangoConnectionState>(() =>
    connectedCache ? "connected" : "loading",
  );
  const [healthDetail, setHealthDetail] = useState(
    () => connectedCache?.detail ?? "",
  );
  const [profileName, setProfileName] = useState(
    () => connectedCache?.profileName ?? "",
  );
  const [connectionMeta, setConnectionMeta] = useState(
    () => connectedCache?.connectionMeta ?? "",
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
      setHealthDetail(result.healthDetail);
      setProfileName(result.profileName);
      setConnectionMeta(result.connectionMeta);
      if (result.health === "connected") {
        writeConnectedCache(
          result.healthDetail,
          result.profileName,
          result.connectionMeta,
        );
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error && err.name === "AbortError"
            ? "Connection check timed out"
            : String(err);

      if (opts.silent && healthRef.current === "connected") {
        return;
      }

      setHealth("failed");
      setHealthDetail("Connection Failed");
      setProfileName("");
      setConnectionMeta("");
      if (!opts.silent && message !== "Connection Failed") {
        setHealthDetail(message);
      }
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

  const refresh = useCallback((opts?: { force?: boolean }) => {
    void runCheck({ silent: false, refresh: Boolean(opts?.force) });
  }, [runCheck]);

  return { health, healthDetail, profileName, connectionMeta, refresh };
}
